"""题目版本的访问权限（纯函数，不访问数据库）。对应设计文档 10.9。

可访问（查看、在自己问卷中使用、基于它创建新版本、查看被哪些问卷使用）——满足任一条件：
1. 自己是版本的所有者；
2. 版本公开（sharing.public）；
3. 自己在 sharing.userIds 中；
4. 版本在一个自己可访问的题库中，且题库创建者按 1~3 现在仍能访问它
   （第 4 条需要查询题库：由 app/services/question_library.py 的 bank_granted 查出
   “通过题库获得访问权的版本 id”，传入 can_access 的 bank_granted 参数）。

只有所有者能做：直接修改未锁定的版本、修改共享设置、删除版本。
不可访问与不存在一样返回 404；可访问但不是所有者却要修改返回 403。
"""
from bson import ObjectId


def is_owner(doc: dict, user_id: ObjectId) -> bool:
    return doc["ownerId"] == user_id


def is_directly_accessible(doc: dict, user_id: ObjectId) -> bool:
    """第 1~3 条：不经过题库就能访问。"""
    sharing = doc.get("sharing") or {}
    return (is_owner(doc, user_id)
            or sharing.get("public") is True
            or user_id in (sharing.get("userIds") or []))


def can_access(doc: dict, user_id: ObjectId, bank_granted: frozenset | set = frozenset()) -> bool:
    return is_directly_accessible(doc, user_id) or doc["_id"] in bank_granted


def direct_access_filter(user_id: ObjectId) -> dict:
    """第 1~3 条对应的查询条件（与 is_directly_accessible 一致，用于列表查询）。"""
    return {"$or": [{"ownerId": user_id}, {"sharing.public": True}, {"sharing.userIds": user_id}]}


def is_locked(doc: dict) -> bool:
    """被问卷用过的版本锁定（10.4 第 2 条）；lockedAt 为 null 或没有该字段表示未锁定。"""
    return doc.get("lockedAt") is not None
