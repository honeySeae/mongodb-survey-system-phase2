"""users 集合的读写（只负责数据库操作，不含业务规则）。"""
from bson import ObjectId
from pymongo.database import Database

from app.db import USERS
from app.utils import now_utc


def create(db: Database, username: str, password_hash: str) -> dict:
    """插入新用户并返回完整文档。用户名重复时抛出 pymongo.errors.DuplicateKeyError。"""
    doc = {"username": username, "passwordHash": password_hash, "createdAt": now_utc()}
    doc["_id"] = db[USERS].insert_one(doc).inserted_id
    return doc


def find_by_username(db: Database, username: str) -> dict | None:
    return db[USERS].find_one({"username": username})


def find_by_id(db: Database, user_id: ObjectId) -> dict | None:
    return db[USERS].find_one({"_id": user_id})


def ids_by_usernames(db: Database, usernames: list[str]) -> dict[str, ObjectId]:
    """批量按用户名取用户 id（命中 username_unique 索引）。"""
    if not usernames:
        return {}
    return {u["username"]: u["_id"] for u in db[USERS].find({"username": {"$in": usernames}}, {"username": 1})}


def usernames_by_ids(db: Database, user_ids) -> dict[ObjectId, str]:
    """批量取用户名（只取 username，不取密码哈希）。"""
    ids = list(set(user_ids))
    if not ids:
        return {}
    return {u["_id"]: u["username"] for u in db[USERS].find({"_id": {"$in": ids}}, {"username": 1})}

