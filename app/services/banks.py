"""题库的业务逻辑（设计文档 10.7、10.9）。

- 题库只存版本的引用 [{questionId, rootId, addedAt}]，不复制内容；选进问卷时才复制（第 5 步的接口）
- 同一个题库里，同一道题（同一 rootId）只能有一项；创建者可以把某一项换成这道题的其他版本
- 加入题库的版本必须是创建者**直接**可访问的（自己的、共享给自己的、公开的）；放进题库不加锁
- 可以共享给指定用户或公开；共享后别人可以查看、使用、基于题库中的版本派生；只有创建者能修改、删除题库
- 条目是否可用实时判断：题库创建者现在仍能直接访问该版本时才可用
- 看不到的题库与不存在一样返回 404；看得到但不是自己的，修改返回 403

并发：加入 / 换版本后再确认版本仍存在（与删除版本同时发生时撤销这一项并返回 404）；
删除版本前会检查是否在任何题库中（第 3 步）。两者交错时总有一方失败。
"""
from dataclasses import dataclass

from bson import ObjectId
from pymongo.database import Database

from app.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.logic import question_access as access
from app.repositories import banks as banks_repo
from app.repositories import questions as questions_repo
from app.repositories import users as users_repo
from app.services import question_library as library
from app.utils import now_utc, parse_object_id

NAME_MAX = 100
DESCRIPTION_MAX = 1000
ITEMS_MAX = 200


def _not_found() -> NotFound:
    return NotFound("BANK_NOT_FOUND", "题库不存在")


def _check_name(name: str) -> list[dict]:
    n = name.strip()
    if not n:
        return [{"field": "name", "message": "题库名称不能为空"}]
    if len(n) > NAME_MAX:
        return [{"field": "name", "message": f"题库名称最多 {NAME_MAX} 个字符"}]
    return []


def _check_description(description: str) -> list[dict]:
    if len(description.strip()) > DESCRIPTION_MAX:
        return [{"field": "description", "message": f"说明最多 {DESCRIPTION_MAX} 个字符"}]
    return []


def can_access(bank: dict, user_id: ObjectId) -> bool:
    sharing = bank["sharing"]
    return bank["ownerId"] == user_id or sharing["public"] is True or user_id in sharing["userIds"]


# ---------- 查询 ----------
def get_accessible(db: Database, user_id: ObjectId, bank_id: str) -> dict:
    oid = parse_object_id(bank_id)
    bank = banks_repo.find(db, oid) if oid else None
    if bank is None or not can_access(bank, user_id):
        raise _not_found()
    return bank


def _get_owned(db: Database, user_id: ObjectId, bank_id: str) -> dict:
    bank = get_accessible(db, user_id, bank_id)
    if bank["ownerId"] != user_id:
        raise Forbidden("NOT_OWNER", "只有题库的创建者能修改题库；你可以使用题库中的题")
    return bank


def list_banks(db: Database, user_id: ObjectId, scope: str, offset: int, limit: int) -> tuple[list[dict], int]:
    """scope：mine 我的 / shared 共享给我的 / public 公开的（不含自己的）/ all 全部可访问的。"""
    query = {
        "mine": {"ownerId": user_id},
        "shared": {"sharing.userIds": user_id, "ownerId": {"$ne": user_id}},
        "public": {"sharing.public": True, "ownerId": {"$ne": user_id}},
        "all": {"$or": [{"ownerId": user_id}, {"sharing.public": True}, {"sharing.userIds": user_id}]},
    }[scope]
    return banks_repo.list_matching(db, query, offset, limit)


@dataclass
class ResolvedItem:
    """题库中的一项及其状态。

    version：可用时为该版本，不可用时为 None（题库创建者已不能直接访问该版本，如原作者取消了共享）。
    以下两项只对题库创建者给出（只有创建者能换版本、移除），其他人为 None：
    newer：可以换成的版本——这道题中创建者能直接访问、版本号比当前大的最新版本；
           当前版本不可用时，为创建者能直接访问的最新版本（不论版本号大小）。
    notice：给创建者的提示文字（有新版本可换；不可用的原因和处理办法）。
    """
    item: dict
    version: dict | None
    newer: dict | None = None
    notice: str | None = None


def resolve_items(db: Database, bank: dict, viewer_id: ObjectId) -> list[ResolvedItem]:
    owner_id = bank["ownerId"]
    ids = [item["questionId"] for item in bank["items"]]
    docs = {d["_id"]: d for d in questions_repo.find_many(db, ids)}
    is_owner = viewer_id == owner_id
    by_root: dict[ObjectId, list[dict]] = {}
    if is_owner:
        # 一次查出所有条目所属题目的全部版本（命中 rootId_version_unique 索引）
        for v in questions_repo.find_by_roots(db, [item["rootId"] for item in bank["items"]]):
            if access.is_directly_accessible(v, owner_id):
                by_root.setdefault(v["rootId"], []).append(v)

    result = []
    for item in bank["items"]:
        doc = docs.get(item["questionId"])
        usable = doc is not None and access.is_directly_accessible(doc, owner_id)
        resolved = ResolvedItem(item=item, version=doc if usable else None)
        if is_owner:
            candidates = [v for v in by_root.get(item["rootId"], []) if v["_id"] != item["questionId"]]
            if usable:
                candidates = [v for v in candidates if v["version"] > doc["version"]]
            resolved.newer = max(candidates, key=lambda v: v["version"], default=None)
            resolved.notice = _owner_notice(db, doc, usable, resolved.newer)
        result.append(resolved)
    return result


def _owner_notice(db: Database, doc: dict | None, usable: bool, newer: dict | None) -> str | None:
    if usable:
        return f"有新版本 v{newer['version']} 可换" if newer else None
    if doc is None:
        reason = "这个版本已不存在"
    else:
        author = users_repo.usernames_by_ids(db, [doc["ownerId"]]).get(doc["ownerId"], "原作者")
        reason = f"原作者 {author} 已取消共享（或不再公开）这道题，你已不能使用这个版本"
    action = f"请移除这一项，或换成 v{newer['version']}" if newer else "请移除这一项"
    return f"{reason}；{action}"


# ---------- 创建、修改、删除 ----------
def create_bank(db: Database, owner_id: ObjectId, *, name: str, description: str | None) -> dict:
    description = description or ""
    errors = _check_name(name) + _check_description(description)
    if errors:
        raise ValidationFailed(errors)
    now = now_utc()
    return banks_repo.insert(db, {
        "ownerId": owner_id, "name": name.strip(), "description": description.strip(), "items": [],
        "sharing": {"public": False, "userIds": []}, "createdAt": now, "updatedAt": now,
    })


def update_bank(db: Database, user_id: ObjectId, bank_id: str, changes: dict) -> dict:
    """修改名称、说明（只提交要改的字段）。"""
    bank = _get_owned(db, user_id, bank_id)
    errors, fields = [], {}
    if changes.get("name") is not None:
        errors += _check_name(changes["name"])
        fields["name"] = changes["name"].strip()
    if changes.get("description") is not None:
        errors += _check_description(changes["description"])
        fields["description"] = changes["description"].strip()
    if errors:
        raise ValidationFailed(errors)
    if not fields:
        return bank
    updated = banks_repo.update_owned(db, bank["_id"], user_id, {"$set": {**fields, "updatedAt": now_utc()}})
    if updated is None:
        raise _not_found()
    return updated


def delete_bank(db: Database, user_id: ObjectId, bank_id: str) -> None:
    """删除题库不影响问卷（问卷里是副本），也不影响题目版本。"""
    bank = _get_owned(db, user_id, bank_id)
    if not banks_repo.delete_owned(db, bank["_id"], user_id):
        raise _not_found()


def set_sharing(db: Database, user_id: ObjectId, bank_id: str, *, public: bool, usernames: list[str]) -> dict:
    """整体替换题库的共享设置（规则与题目共享相同）。"""
    bank = _get_owned(db, user_id, bank_id)
    sharing = library.resolve_sharing(db, user_id, public=public, usernames=usernames)
    updated = banks_repo.update_owned(db, bank["_id"], user_id,
                                      {"$set": {"sharing": sharing, "updatedAt": now_utc()}})
    if updated is None:
        raise _not_found()
    return updated


# ---------- 条目 ----------
def _version_for_item(db: Database, user_id: ObjectId, question_id: str) -> dict:
    """加入题库的版本：自己能访问，且是直接访问（不能只通过别人的题库访问，避免题库套题库）。"""
    doc = library.get_accessible(db, user_id, question_id)
    if not access.is_directly_accessible(doc, user_id):
        raise Forbidden("NOT_DIRECTLY_ACCESSIBLE",
                        "只能加入自己的、共享给你的或公开的题目；通过别人的题库看到的题不能再加入题库")
    return doc


def _confirm_still_exists(db: Database, user_id: ObjectId, bank: dict, doc: dict,
                          undo: dict, undo_filter: dict | None = None) -> None:
    """加入 / 换版本之后确认版本仍存在；期间被删除时撤销这次修改并返回 404。"""
    if questions_repo.find(db, doc["_id"]) is None:
        banks_repo.update_owned(db, bank["_id"], user_id, undo, extra_filter=undo_filter)
        raise NotFound("QUESTION_NOT_FOUND", "题目不存在")


def add_item(db: Database, user_id: ObjectId, bank_id: str, question_id: str) -> dict:
    bank = _get_owned(db, user_id, bank_id)
    doc = _version_for_item(db, user_id, question_id)
    root_id = doc["rootId"]
    item = {"questionId": doc["_id"], "rootId": root_id, "addedAt": now_utc()}
    updated = banks_repo.update_owned(
        db, bank["_id"], user_id,
        {"$push": {"items": item}, "$set": {"updatedAt": item["addedAt"]}},
        extra_filter={"items.rootId": {"$ne": root_id}, f"items.{ITEMS_MAX - 1}": {"$exists": False}})
    if updated is None:
        current = banks_repo.find(db, bank["_id"])
        if current is None:
            raise _not_found()
        if any(i["rootId"] == root_id for i in current["items"]):
            raise Conflict("ALREADY_IN_BANK", "这道题已经在题库中（同一道题只能有一项）；可以把它换成其他版本")
        raise ValidationFailed([{"field": "items", "message": f"每个题库最多 {ITEMS_MAX} 道题"}])
    _confirm_still_exists(db, user_id, bank, doc, {"$pull": {"items": {"questionId": doc["_id"]}}})
    return updated


def _parse_root(root_id: str) -> ObjectId:
    oid = parse_object_id(root_id)
    if oid is None:
        raise NotFound("ITEM_NOT_FOUND", "题库中没有这道题")
    return oid


def switch_item(db: Database, user_id: ObjectId, bank_id: str, root_id: str, question_id: str) -> dict:
    """把某一项换成这道题的另一个版本（不会自动跟随新版本，由创建者手动更换）。"""
    bank = _get_owned(db, user_id, bank_id)
    root = _parse_root(root_id)
    old = next((i for i in bank["items"] if i["rootId"] == root), None)
    if old is None:
        raise NotFound("ITEM_NOT_FOUND", "题库中没有这道题")
    doc = _version_for_item(db, user_id, question_id)
    if doc["rootId"] != root:
        raise ValidationFailed([{"field": "questionId",
                                 "message": "只能换成同一道题的其他版本；要加入另一道题请添加新的一项"}])
    if doc["_id"] == old["questionId"]:
        return bank
    updated = banks_repo.update_owned(
        db, bank["_id"], user_id,
        {"$set": {"items.$.questionId": doc["_id"], "updatedAt": now_utc()}},
        extra_filter={"items.rootId": root})
    if updated is None:
        raise NotFound("ITEM_NOT_FOUND", "题库中没有这道题")
    _confirm_still_exists(db, user_id, bank, doc, {"$set": {"items.$.questionId": old["questionId"]}},
                          undo_filter={"items.questionId": doc["_id"]})
    return updated


def remove_item(db: Database, user_id: ObjectId, bank_id: str, root_id: str) -> dict:
    bank = _get_owned(db, user_id, bank_id)
    root = _parse_root(root_id)
    updated = banks_repo.update_owned(
        db, bank["_id"], user_id,
        {"$pull": {"items": {"rootId": root}}, "$set": {"updatedAt": now_utc()}},
        extra_filter={"items.rootId": root})
    if updated is None:
        raise NotFound("ITEM_NOT_FOUND", "题库中没有这道题")
    return updated
