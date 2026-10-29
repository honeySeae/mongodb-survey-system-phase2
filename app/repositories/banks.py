"""questionBanks 集合（题库）的读写（只负责数据库操作，不含业务规则）。对应设计文档 10.7。

条目的增删改都用数组更新运算符原子完成（不读出整个题库再写回），条件中带 ownerId：只有创建者能修改。
"""
from bson import ObjectId
from pymongo import ReturnDocument
from pymongo.database import Database

from app.db import QUESTION_BANKS


def _accessible_filter(user_id: ObjectId) -> dict:
    return {"$or": [{"ownerId": user_id}, {"sharing.public": True}, {"sharing.userIds": user_id}]}


def insert(db: Database, doc: dict) -> dict:
    doc["_id"] = db[QUESTION_BANKS].insert_one(doc).inserted_id
    return doc


def find(db: Database, bank_id: ObjectId) -> dict | None:
    return db[QUESTION_BANKS].find_one({"_id": bank_id})


def list_matching(db: Database, query: dict, offset: int, limit: int) -> tuple[list[dict], int]:
    """题库列表（最近修改的在前），不返回条目，只返回条目数。"""
    total = db[QUESTION_BANKS].count_documents(query)
    pipeline = [
        {"$match": query},
        {"$sort": {"updatedAt": -1, "_id": -1}},
        {"$skip": offset},
        {"$limit": limit},
        {"$addFields": {"itemCount": {"$size": "$items"}}},
        {"$project": {"items": 0}},
    ]
    return list(db[QUESTION_BANKS].aggregate(pipeline)), total


def accessible_banks_containing(db: Database, user_id: ObjectId, question_ids: list[ObjectId]) -> list[dict]:
    """自己可访问的、包含这些版本中任意一个的题库（只取创建者和条目），用于“通过题库获得访问权”。"""
    if not question_ids:
        return []
    query = {"$and": [{"items.questionId": {"$in": question_ids}}, _accessible_filter(user_id)]}
    return list(db[QUESTION_BANKS].find(query, {"ownerId": 1, "items.questionId": 1}))


def update_owned(db: Database, bank_id: ObjectId, owner_id: ObjectId, update: dict,
                 extra_filter: dict | None = None) -> dict | None:
    """仅当题库属于 owner（且满足 extra_filter）时更新，返回更新后的题库；不满足时返回 None。"""
    query = {"_id": bank_id, "ownerId": owner_id, **(extra_filter or {})}
    return db[QUESTION_BANKS].find_one_and_update(query, update, return_document=ReturnDocument.AFTER)


def delete_owned(db: Database, bank_id: ObjectId, owner_id: ObjectId) -> bool:
    return db[QUESTION_BANKS].delete_one({"_id": bank_id, "ownerId": owner_id}).deleted_count == 1
