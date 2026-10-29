"""题目与版本的业务逻辑：新建、列表、详情、直接修改、派生新版本、恢复、历史、删除。

对应设计文档 10.2、10.4、10.6（继承共享设置）、10.9（权限与删除）。
内容规则在 app/logic/question_versions.py，权限判断在 app/logic/question_access.py。

并发约定（单机 MongoDB 不使用事务）：
- 版本号：取最大版本号 + 1 插入，{rootId, version} 唯一索引冲突时重新取号
- 直接修改：条件更新带 ownerId、lockedAt: null 和读取时的 updatedAt
- 删除与派生同时发生：派生插入后再确认父版本仍存在，不存在就撤销刚插入的版本并返回 404；
  删除先检查没有子版本再删。两者交错时，要么派生失败，要么删除失败，不会留下父版本不存在的版本
"""
from datetime import datetime, timedelta

from bson import ObjectId
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

from app.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.logic import question_access as access
from app.logic.question_versions import build_content
from app.repositories import banks as banks_repo
from app.repositories import questions as questions_repo
from app.repositories import users as users_repo
from app.utils import now_utc, parse_object_id, to_mongo_time

VERSION_RETRIES = 5
PRIVATE = {"public": False, "userIds": []}


def _not_found() -> NotFound:
    return NotFound("QUESTION_NOT_FOUND", "题目不存在")


# ---------- 查询与权限 ----------
def bank_granted(db: Database, user_id: ObjectId, docs: list[dict]) -> set[ObjectId]:
    """10.9 第 4 条：这些版本中，通过自己可访问的题库获得访问权的版本 id。

    条件：版本在一个自己可访问的题库中，且题库创建者**现在**仍能直接访问它（第 1~3 条）。
    只对不能直接访问的版本查询题库。
    """
    pending = {d["_id"]: d for d in docs if not access.is_directly_accessible(d, user_id)}
    granted: set[ObjectId] = set()
    for bank in banks_repo.accessible_banks_containing(db, user_id, list(pending)):
        for item in bank["items"]:
            doc = pending.get(item["questionId"])
            if doc is not None and access.is_directly_accessible(doc, bank["ownerId"]):
                granted.add(doc["_id"])
    return granted


def get_accessible(db: Database, user_id: ObjectId, question_id: str) -> dict:
    """取一个自己可访问的版本；id 格式不对、不存在、无权访问，都返回 404。"""
    oid = parse_object_id(question_id)
    doc = questions_repo.find(db, oid) if oid else None
    if doc is None or not access.can_access(doc, user_id, bank_granted(db, user_id, [doc])):
        raise _not_found()
    return doc


def _get_owned(db: Database, user_id: ObjectId, question_id: str, action: str) -> dict:
    """取一个自己拥有的版本：看不到返回 404，看得到但不是自己的返回 403。"""
    doc = get_accessible(db, user_id, question_id)
    if not access.is_owner(doc, user_id):
        raise Forbidden("NOT_OWNER", f"这是别人共享给你的题目，不能{action}；可以基于它创建自己的新版本")
    return doc


def _locked_error() -> Conflict:
    return Conflict("QUESTION_LOCKED", "这个版本已被问卷使用，不能直接修改；请基于它创建新版本")


def list_questions(db: Database, user_id: ObjectId, scope: str, root_id: str | None,
                   offset: int, limit: int) -> tuple[list[dict], int]:
    """题目列表。scope：mine 我的 / shared 共享给我的 / public 公开的（不含自己的）/ all 全部可访问的。"""
    query = {
        "mine": {"ownerId": user_id},
        "shared": {"sharing.userIds": user_id, "ownerId": {"$ne": user_id}},
        "public": {"sharing.public": True, "ownerId": {"$ne": user_id}},
        "all": access.direct_access_filter(user_id),
    }[scope]
    if root_id is not None:
        oid = parse_object_id(root_id)
        if oid is None:
            return [], 0
        query = {"$and": [query, {"rootId": oid}]}
    return questions_repo.list_matching(db, query, offset, limit)


def history(db: Database, user_id: ObjectId, question_id: str) -> tuple[dict, list[tuple[dict, bool]]]:
    """一道题的全部版本（按版本号排序），每项附带自己能否访问。返回 (被查询的版本, [(版本, 可访问)])。"""
    doc = get_accessible(db, user_id, question_id)
    versions = questions_repo.list_versions(db, doc["rootId"])
    granted = bank_granted(db, user_id, versions)
    return doc, [(v, access.can_access(v, user_id, granted)) for v in versions]


# ---------- 新建版本的公共部分 ----------
def _check(problems: list[dict]) -> None:
    if problems:
        raise ValidationFailed(problems, "题目设置不合法")


def _inherited_sharing(db: Database, root_id: ObjectId, owner_id: ObjectId) -> dict:
    """新版本继承自己在这道题上已有的共享设置；还没有版本时默认不共享（10.6）。"""
    mine = questions_repo.latest_owned_in_root(db, root_id, owner_id)
    if mine is None:
        return dict(PRIVATE)
    return {"public": mine["sharing"]["public"], "userIds": list(mine["sharing"]["userIds"])}


def _insert_version(db: Database, owner_id: ObjectId, root_id: ObjectId, parent_id: ObjectId,
                    content: dict, restored_from: ObjectId | None = None) -> dict:
    """在已有的一道题下插入新版本：版本号取最大值 + 1，冲突时重试；插入后确认父版本仍存在。"""
    sharing = _inherited_sharing(db, root_id, owner_id)
    for _ in range(VERSION_RETRIES):
        now = now_utc()
        doc = {
            "rootId": root_id, "parentId": parent_id,
            "version": questions_repo.max_version(db, root_id) + 1,
            "ownerId": owner_id, **content, "sharing": sharing,
            "lockedAt": None, "createdAt": now, "updatedAt": now,
        }
        if restored_from is not None:
            doc["restoredFrom"] = restored_from
        try:
            questions_repo.insert(db, doc)
            break
        except DuplicateKeyError:
            doc.pop("_id", None)
            continue
    else:
        raise Conflict("VERSION_CONFLICT", "同时创建版本的人太多，请稍后重试")

    # 父版本（以及恢复的来源版本）可能在此期间被删除：撤销刚插入的版本
    for ref in {parent_id, restored_from} - {None}:
        if questions_repo.find(db, ref) is None:
            questions_repo.delete(db, doc["_id"])
            raise _not_found()

    # 插入前读到的共享设置可能已被同时进行的“修改共享”改掉（它的 updateMany 没有包含这个新版本）：
    # 插入后再与自己的其他版本对齐一次。修改共享若发生在插入之后，updateMany 本身就会包含新版本
    other = questions_repo.latest_owned_in_root(db, root_id, owner_id, exclude_id=doc["_id"])
    if other is not None and other["sharing"] != doc["sharing"]:
        questions_repo.set_sharing(db, doc["_id"], other["sharing"])
        doc["sharing"] = other["sharing"]
    return doc


# ---------- 新建题目（v1） ----------
def create_question(db: Database, owner_id: ObjectId, *, qtype: str, title: str,
                    options: list[dict] | None, validation: dict | None) -> dict:
    content, problems = build_content(qtype=qtype, title=title, options=options, validation=validation)
    _check(problems)
    qid, now = ObjectId(), now_utc()
    doc = {
        "_id": qid, "rootId": qid, "parentId": None, "version": 1, "ownerId": owner_id,
        **content, "sharing": dict(PRIVATE), "lockedAt": None, "createdAt": now, "updatedAt": now,
    }
    return questions_repo.insert(db, doc)


# ---------- 派生新版本 ----------
def derive_version(db: Database, user_id: ObjectId, question_id: str, *, qtype: str, title: str,
                   options: list[dict] | None, validation: dict | None) -> dict:
    """基于一个可访问的版本创建自己的新版本（锁定与否都可以；未锁定时即“另存为新版本”）。"""
    base = get_accessible(db, user_id, question_id)
    used = questions_repo.used_option_ids(db, base["rootId"])
    content, problems = build_content(qtype=qtype, title=title, options=options, validation=validation,
                                      base=base, used_option_ids=used)
    _check(problems)
    return _insert_version(db, user_id, base["rootId"], base["_id"], content)


# ---------- 直接修改未锁定的版本 ----------
def update_version(db: Database, user_id: ObjectId, question_id: str, *, qtype: str, title: str,
                   options: list[dict] | None, validation: dict | None,
                   expected_updated_at: datetime | None = None) -> dict:
    doc = _get_owned(db, user_id, question_id, "直接修改")
    if access.is_locked(doc):
        raise _locked_error()
    if expected_updated_at is not None and to_mongo_time(expected_updated_at) != doc["updatedAt"]:
        raise Conflict("EDIT_CONFLICT", "题目已被修改，请刷新后重试")
    used = questions_repo.used_option_ids(db, doc["rootId"])
    content, problems = build_content(qtype=qtype, title=title, options=options, validation=validation,
                                      base=doc, used_option_ids=used)
    _check(problems)
    now = max(now_utc(), doc["updatedAt"] + timedelta(milliseconds=1))
    updated = questions_repo.update_unlocked(db, doc["_id"], user_id, {**content, "updatedAt": now},
                                             extra_filter={"updatedAt": doc["updatedAt"]})
    if updated is None:
        current = questions_repo.find(db, doc["_id"])
        if current is None:
            raise _not_found()
        if access.is_locked(current):
            raise _locked_error()
        raise Conflict("EDIT_CONFLICT", "题目已被修改，请刷新后重试")
    return updated


# ---------- 恢复旧版本 ----------
def restore_version(db: Database, user_id: ObjectId, question_id: str, parent_id: str | None) -> dict:
    """把 question_id 的内容复制成一个新版本（restoredFrom = question_id）。

    parent_id：接在哪个版本后面；不指定时接在自己在这道题下版本号最大的版本后面，
    自己还没有版本时接在被恢复的版本后面（10.4 第 5 条）。
    """
    source = get_accessible(db, user_id, question_id)
    if parent_id is not None:
        parent = get_accessible(db, user_id, parent_id)
        if parent["rootId"] != source["rootId"]:
            raise ValidationFailed([{"field": "parentId",
                                     "message": "只能接在同一道题的版本后面"}])
    else:
        parent = questions_repo.latest_owned_in_root(db, source["rootId"], user_id) or source
    content = {k: source[k] for k in ("type", "title", "options", "validation") if k in source}
    return _insert_version(db, user_id, source["rootId"], parent["_id"], content,
                           restored_from=source["_id"])


# ---------- 把问卷里的题存进题目库（10.5） ----------
def create_from_survey_question(db: Database, owner_id: ObjectId, question: dict) -> dict:
    """用问卷中一道题的内容生成新题 v1：选项 id 沿用，validation 去掉 required，不含跳转规则。
    这道题已被该问卷使用，所以 v1 创建时即锁定。"""
    qid, now = ObjectId(), now_utc()
    content = {k: question[k] for k in ("type", "title", "options") if k in question}
    content["validation"] = {k: v for k, v in question["validation"].items() if k != "required"}
    doc = {
        "_id": qid, "rootId": qid, "parentId": None, "version": 1, "ownerId": owner_id,
        **content, "sharing": dict(PRIVATE), "lockedAt": now, "createdAt": now, "updatedAt": now,
    }
    return questions_repo.insert(db, doc)


def discard(db: Database, question_id: ObjectId) -> None:
    """撤销刚创建、尚未被使用的版本（存入题目库失败时）。"""
    questions_repo.delete(db, question_id)


# ---------- 加进问卷前加锁（10.4 第 2 条、10.5） ----------
def lock_for_use(db: Database, user_id: ObjectId, question_id: str) -> dict:
    """取一个可访问的版本并加锁，返回加锁后的版本（内容从此不再变化，可以复制进问卷）。

    先加锁再复制：与“直接修改”同时发生时，要么修改先完成（复制的是修改后的内容），
    要么加锁先完成（修改因 lockedAt 条件失败），问卷里的副本一定与版本内容一致。
    """
    doc = get_accessible(db, user_id, question_id)
    locked = questions_repo.lock(db, doc["_id"], now_utc())
    if locked is None:  # 期间被删除
        raise _not_found()
    return locked


SNAPSHOT_FIELDS = ("type", "title", "options", "validation")


def snapshot(doc: dict) -> dict:
    """版本内容的副本（复制进问卷的部分），不含版本信息和共享设置。"""
    return {k: doc[k] for k in SNAPSHOT_FIELDS if k in doc}


def source_of(doc: dict) -> dict:
    """问卷题目的 source 字段（10.3）。"""
    return {"questionId": doc["_id"], "rootId": doc["rootId"], "version": doc["version"]}


# ---------- 共享（10.6） ----------
SHARE_USERS_MAX = 100


def set_sharing(db: Database, user_id: ObjectId, question_id: str, *, public: bool,
                usernames: list[str]) -> tuple[dict, int]:
    """设置自己在这道题下所有版本的共享：指定用户（按用户名）和是否公开。整体替换原设置。

    返回 (更新后的版本, 更新的版本数)。只有所有者能设置；不能共享给自己；用户名不存在时报错。
    取消共享不影响已经复制进别人问卷的题（问卷里是副本）。
    """
    doc = _get_owned(db, user_id, question_id, "修改共享设置")
    sharing = resolve_sharing(db, user_id, public=public, usernames=usernames)
    count = questions_repo.set_sharing_for_owner_in_root(db, doc["rootId"], user_id, sharing)
    doc["sharing"] = sharing
    return doc, count


def resolve_sharing(db: Database, user_id: ObjectId, *, public: bool, usernames: list[str]) -> dict:
    """把共享请求转换为存库的 sharing（题目、题库共用）：用户名去首尾空格、去重；
    不存在的用户、共享给自己、超过上限时报错。"""
    names = list(dict.fromkeys(n.strip() for n in usernames))  # 去掉首尾空格、去重、保持顺序
    if len(names) > SHARE_USERS_MAX:
        raise ValidationFailed([{"field": "usernames", "message": f"最多共享给 {SHARE_USERS_MAX} 个用户"}],
                               "共享设置不合法")
    found = users_repo.ids_by_usernames(db, names)
    errors = []
    for i, name in enumerate(names):
        if name not in found:
            errors.append({"field": f"usernames[{i}]", "message": f"用户「{name}」不存在"})
        elif found[name] == user_id:
            errors.append({"field": f"usernames[{i}]", "message": "不能共享给自己"})
    if errors:
        raise ValidationFailed(errors, "共享设置不合法")
    return {"public": public, "userIds": [found[n] for n in names]}


# ---------- 删除 ----------
def delete_version(db: Database, user_id: ObjectId, question_id: str) -> None:
    """只有所有者能删；被问卷用过、有子版本、被任何题库引用的版本不能删（10.9）。"""
    doc = _get_owned(db, user_id, question_id, "删除")
    if access.is_locked(doc):
        raise Conflict("QUESTION_LOCKED", "这个版本已被问卷使用，不能删除")
    if questions_repo.has_children(db, doc["_id"]):
        raise Conflict("QUESTION_HAS_CHILDREN", "已有其他版本从这个版本派生或恢复，不能删除")
    if questions_repo.in_any_bank(db, doc["_id"]):
        raise Conflict("QUESTION_IN_BANK", "这个版本在题库中，不能删除")
    if not questions_repo.delete_unlocked(db, doc["_id"], user_id):
        # 检查之后被加进了问卷（已加锁）
        raise Conflict("QUESTION_LOCKED", "这个版本已被问卷使用，不能删除")
