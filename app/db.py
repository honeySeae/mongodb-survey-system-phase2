"""MongoDB 连接。

整个进程共用一个 MongoClient（PyMongo 的客户端自带连接池、线程安全），
首次使用时创建，应用关闭时释放。
"""
from pymongo import MongoClient
from pymongo.database import Database

from app.config import get_settings

# 集合名集中定义，其他模块引用常量而不是直接写字符串
USERS = "users"
SURVEYS = "surveys"
RESPONSES = "responses"
# 第二阶段新增（设计文档第十节）
QUESTIONS = "questions"
QUESTION_BANKS = "questionBanks"

_client: MongoClient | None = None


def get_client() -> MongoClient:
    global _client
    if _client is None:
        settings = get_settings()
        # tz_aware：读出的时间带时区（UTC），避免与 datetime.now(timezone.utc) 比较时出错
        _client = MongoClient(settings.mongo_uri, tz_aware=True, serverSelectionTimeoutMS=5000)
    return _client


def get_db() -> Database:
    return get_client()[get_settings().mongo_db_name]


def close_client() -> None:
    global _client
    if _client is not None:
        _client.close()
        _client = None


def ping() -> bool:
    """数据库是否可连接。"""
    try:
        get_client().admin.command("ping")
        return True
    except Exception:
        return False
