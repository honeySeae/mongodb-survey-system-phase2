"""questions 集合（题目版本）的读写（只负责数据库操作，不含业务规则）。对应设计文档 10.2。"""
from bson import ObjectId
from pymongo import DESCENDING, ReturnDocument
from pymongo.database import Database

from app.db import QUESTION_BANKS, QUESTIONS


def insert(db: Database, doc: dict) -> dict:
    """插入一个版本；{rootId, version} 重复时抛出 DuplicateKeyError（由调用方重新取号）。"""
    doc["_id"] = db[QUESTIONS].insert_one(doc).inserted_id
    return doc


def find(db: Database, question_id: ObjectId) -> dict | None:
    return db[QUESTIONS].find_one({"_id": question_id})


def find_many(db: Database, question_ids: list[ObjectId]) -> list[dict]:
    if not question_ids:
        return []
    return list(db[QUESTIONS].find({"_id": {"$in": question_ids}}))


def max_version(db: Database, root_id: ObjectId) -> int:
    """这道题现有的最大版本号（命中 rootId_version_unique 索引）。"""
    doc = db[QUESTIONS].find_one({"rootId": root_id}, {"version": 1}, sort=[("version", DESCENDING)])
    return doc["version"] if doc else 0


def list_versions(db: Database, root_id: ObjectId) -> list[dict]:
    """一道题的全部版本，按版本号排序。"""
    return list(db[QUESTIONS].find({"rootId": root_id}).sort("version", 1))


def used_option_ids(db: Database, root_id: ObjectId) -> set[str]:
    """这道题所有版本中用过的选项 id。"""
    ids: set[str] = set()
    for doc in db[QUESTIONS].find({"rootId": root_id}, {"options.id": 1}):
        ids.update(o["id"] for o in doc.get("options") or [])
    return ids


def latest_owned_in_root(db: Database, root_id: ObjectId, owner_id: ObjectId,
                         exclude_id: ObjectId | None = None) -> dict | None:
    """自己在这道题下版本号最大的版本（恢复时默认的父版本、新版本继承共享设置）。"""
    query = {"rootId": root_id, "ownerId": owner_id}
    if exclude_id is not None:
        query["_id"] = {"$ne": exclude_id}
    return db[QUESTIONS].find_one(query, sort=[("version", DESCENDING)])


def list_matching(db: Database, query: dict, offset: int, limit: int) -> tuple[list[dict], int]:
    """按条件列出版本（最近修改的在前），返回 (本页, 总数)。"""
    total = db[QUESTIONS].count_documents(query)
    docs = list(db[QUESTIONS].find(query).sort([("updatedAt", -1), ("_id", -1)]).skip(offset).limit(limit))
    return docs, total


def set_sharing_for_owner_in_root(db: Database, root_id: ObjectId, owner_id: ObjectId,
                                  sharing: dict) -> int:
    """以整道题为单位共享：一次更新 owner 在这道题下的所有版本（10.6），返回更新的版本数。
    只改 sharing，不改 updatedAt（共享设置不是题目内容的修改，不影响编辑冲突检查）。"""
    result = db[QUESTIONS].update_many({"rootId": root_id, "ownerId": owner_id},
                                       {"$set": {"sharing": sharing}})
    return result.matched_count


def set_sharing(db: Database, question_id: ObjectId, sharing: dict) -> None:
    db[QUESTIONS].update_one({"_id": question_id}, {"$set": {"sharing": sharing}})


def update_unlocked(db: Database, question_id: ObjectId, owner_id: ObjectId,
                    set_fields: dict, extra_filter: dict | None = None) -> dict | None:
    """仅当版本属于 owner 且未锁定时才更新（条件更新：与“加进问卷时加锁”同时发生时只有一个成功）。"""
    query = {"_id": question_id, "ownerId": owner_id, "lockedAt": None}
    if extra_filter:
        query.update(extra_filter)
    return db[QUESTIONS].find_one_and_update(query, {"$set": set_fields},
                                             return_document=ReturnDocument.AFTER)


def has_children(db: Database, question_id: ObjectId) -> bool:
    """是否有别的版本从它派生（parentId）或恢复自它（restoredFrom）。"""
    return db[QUESTIONS].find_one(
        {"$or": [{"parentId": question_id}, {"restoredFrom": question_id}]}, {"_id": 1}) is not None


def in_any_bank(db: Database, question_id: ObjectId) -> bool:
    """是否被任何人的题库引用（命中 items_questionId 索引）。"""
    return db[QUESTION_BANKS].find_one({"items.questionId": question_id}, {"_id": 1}) is not None


def lock(db: Database, question_id: ObjectId, now) -> dict | None:
    """加锁（10.4 第 2 条）：未锁定时置上 lockedAt，已锁定的保持原值；返回加锁后的版本，不存在时返回 None。
    加锁后内容不会再变（直接修改的条件带 lockedAt: null），调用方用返回的内容复制进问卷。"""
    db[QUESTIONS].update_one({"_id": question_id, "lockedAt": None}, {"$set": {"lockedAt": now}})
    return db[QUESTIONS].find_one({"_id": question_id})


def delete_unlocked(db: Database, question_id: ObjectId, owner_id: ObjectId) -> bool:
    result = db[QUESTIONS].delete_one({"_id": question_id, "ownerId": owner_id, "lockedAt": None})
    return result.deleted_count == 1


def delete(db: Database, question_id: ObjectId) -> None:
    db[QUESTIONS].delete_one({"_id": question_id})
