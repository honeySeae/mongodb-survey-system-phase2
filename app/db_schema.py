"""集合的 $jsonSchema 校验和索引定义（对应 docs/DATABASE_DESIGN.md 第 2~5 节；第二阶段见 10.10）。

ensure_schema() 是幂等的：集合不存在则创建，已存在则用 collMod 更新校验规则；
索引已存在则跳过。应用启动和 scripts/init_db.py 都会调用它。

校验策略（设计文档 5.1）：
- 只约束核心字段的必填、类型和枚举取值，更细的业务校验在应用层完成；
- 不设置 additionalProperties: false，第二阶段新增字段不会被数据库拒绝；
- validationLevel 为 moderate：已存在的不合规旧文档仍可更新，不会因规则变化而“卡死”。
"""
from pymongo import ASCENDING, DESCENDING, IndexModel
from pymongo.database import Database

from app.db import QUESTION_BANKS, QUESTIONS, RESPONSES, SURVEYS, USERS

# ---------- 取值枚举（与设计文档一致，供应用层复用） ----------
SURVEY_STATUSES = ["draft", "published", "closed"]
SUBMISSION_POLICIES = ["once", "latest", "all"]
QUESTION_TYPES = ["single_choice", "multiple_choice", "text", "number"]

# MongoDB 中整数可能是 int（32 位）或 long（64 位），统一接受
_INT = ["int", "long"]

# ---------- $jsonSchema ----------
USERS_SCHEMA = {
    "bsonType": "object",
    "required": ["username", "passwordHash", "createdAt"],
    "properties": {
        "username": {"bsonType": "string", "minLength": 1},
        "passwordHash": {"bsonType": "string", "minLength": 1},
        "createdAt": {"bsonType": "date"},
    },
}

_OPTION_SCHEMA = {
    "bsonType": "object",
    "required": ["id", "text"],
    "properties": {
        "id": {"bsonType": "string"},
        "text": {"bsonType": "string"},
    },
}

_QUESTION_SCHEMA = {
    "bsonType": "object",
    "required": ["id", "type", "title", "validation"],
    "properties": {
        "id": {"bsonType": "string"},
        "type": {"enum": QUESTION_TYPES},
        "title": {"bsonType": "string"},
        "options": {"bsonType": "array", "items": _OPTION_SCHEMA},
        "validation": {"bsonType": "object"},
        "logic": {"bsonType": "object"},
        # 第二阶段：来自题库的题记录来源版本（10.3）；可选，第一阶段的题没有该字段
        "source": {
            "bsonType": "object",
            "required": ["questionId", "rootId", "version"],
            "properties": {
                "questionId": {"bsonType": "objectId"},
                "rootId": {"bsonType": "objectId"},
                "version": {"bsonType": _INT, "minimum": 1},
            },
        },
    },
}

SURVEYS_SCHEMA = {
    "bsonType": "object",
    "required": [
        "ownerId", "shortCode", "title", "status", "settings",
        "version", "questions", "createdAt", "updatedAt",
    ],
    "properties": {
        "ownerId": {"bsonType": "objectId"},
        "shortCode": {"bsonType": "string", "minLength": 1},
        "title": {"bsonType": "string", "minLength": 1},
        "description": {"bsonType": "string"},
        "status": {"enum": SURVEY_STATUSES},
        "settings": {
            "bsonType": "object",
            "required": ["allowAnonymous", "submissionPolicy"],
            "properties": {
                "allowAnonymous": {"bsonType": "bool"},
                "submissionPolicy": {"enum": SUBMISSION_POLICIES},
                "deadline": {"bsonType": ["date", "null"]},
            },
        },
        "version": {"bsonType": _INT, "minimum": 1},
        "questions": {"bsonType": "array", "items": _QUESTION_SCHEMA},
        "createdAt": {"bsonType": "date"},
        "updatedAt": {"bsonType": "date"},
        "publishedAt": {"bsonType": ["date", "null"]},
        "closedAt": {"bsonType": ["date", "null"]},
    },
}

RESPONSES_SCHEMA = {
    "bsonType": "object",
    "required": [
        "surveyId", "surveyVersion", "respondentId", "isLatest", "submittedAt", "answers",
    ],
    "properties": {
        "surveyId": {"bsonType": "objectId"},
        "surveyVersion": {"bsonType": _INT, "minimum": 1},
        "respondentId": {"bsonType": "objectId"},
        "isLatest": {"bsonType": "bool"},
        "submittedAt": {"bsonType": "date"},
        "answers": {
            "bsonType": "array",
            "items": {
                # value 的类型随题型变化（字符串 / 数组 / 数值），由应用层校验
                "bsonType": "object",
                "required": ["questionId", "value"],
                "properties": {"questionId": {"bsonType": "string"}},
            },
        },
    },
}

# ---------- 第二阶段（设计文档 10.2、10.7） ----------
_SHARING_SCHEMA = {
    "bsonType": "object",
    "required": ["public", "userIds"],
    "properties": {
        "public": {"bsonType": "bool"},
        "userIds": {"bsonType": "array", "items": {"bsonType": "objectId"}},
    },
}

QUESTIONS_SCHEMA = {
    "bsonType": "object",
    "required": [
        "rootId", "version", "ownerId", "type", "title", "validation",
        "sharing", "createdAt", "updatedAt",
    ],
    "properties": {
        "rootId": {"bsonType": "objectId"},
        "parentId": {"bsonType": ["objectId", "null"]},
        "restoredFrom": {"bsonType": ["objectId", "null"]},
        "version": {"bsonType": _INT, "minimum": 1},
        "ownerId": {"bsonType": "objectId"},
        "type": {"enum": QUESTION_TYPES},
        "title": {"bsonType": "string", "minLength": 1},
        "options": {"bsonType": "array", "items": _OPTION_SCHEMA},
        # 是否必答由问卷决定，题目版本中不存 required
        "validation": {"bsonType": "object", "not": {"required": ["required"]}},
        "sharing": _SHARING_SCHEMA,
        "lockedAt": {"bsonType": ["date", "null"]},
        "createdAt": {"bsonType": "date"},
        "updatedAt": {"bsonType": "date"},
    },
}

QUESTION_BANKS_SCHEMA = {
    "bsonType": "object",
    "required": ["ownerId", "name", "items", "sharing", "createdAt", "updatedAt"],
    "properties": {
        "ownerId": {"bsonType": "objectId"},
        "name": {"bsonType": "string", "minLength": 1},
        "description": {"bsonType": "string"},
        "items": {
            "bsonType": "array",
            "items": {
                "bsonType": "object",
                "required": ["questionId", "rootId", "addedAt"],
                "properties": {
                    "questionId": {"bsonType": "objectId"},
                    "rootId": {"bsonType": "objectId"},
                    "addedAt": {"bsonType": "date"},
                },
            },
        },
        "sharing": _SHARING_SCHEMA,
        "createdAt": {"bsonType": "date"},
        "updatedAt": {"bsonType": "date"},
    },
}

SCHEMAS = {
    USERS: USERS_SCHEMA,
    SURVEYS: SURVEYS_SCHEMA,
    RESPONSES: RESPONSES_SCHEMA,
    QUESTIONS: QUESTIONS_SCHEMA,
    QUESTION_BANKS: QUESTION_BANKS_SCHEMA,
}

# ---------- 索引（设计文档第 5 节），统一显式命名 ----------
INDEXES = {
    USERS: [
        IndexModel([("username", ASCENDING)], name="username_unique", unique=True),
    ],
    SURVEYS: [
        IndexModel([("shortCode", ASCENDING)], name="shortCode_unique", unique=True),
        IndexModel([("ownerId", ASCENDING), ("createdAt", DESCENDING)], name="ownerId_createdAt"),
        # 第二阶段：某个版本 / 某道题被哪些问卷使用；跨问卷统计找自己的问卷
        IndexModel([("questions.source.questionId", ASCENDING)], name="questions_source_questionId"),
        IndexModel([("questions.source.rootId", ASCENDING), ("ownerId", ASCENDING)],
                   name="questions_source_rootId_ownerId"),
    ],
    RESPONSES: [
        IndexModel([("surveyId", ASCENDING), ("submittedAt", DESCENDING)], name="surveyId_submittedAt"),
        # 每人每份问卷最多一份“最新”答卷；也用于判断是否填写过（查询带 isLatest: true）
        IndexModel(
            [("surveyId", ASCENDING), ("respondentId", ASCENDING)],
            name="surveyId_respondentId_latest_unique",
            unique=True,
            partialFilterExpression={"isLatest": True},
        ),
        IndexModel([("answers.questionId", ASCENDING)], name="answers_questionId"),
    ],
    # ---------- 第二阶段（设计文档 10.10） ----------
    QUESTIONS: [
        # 一道题的全部版本；版本号不重复（并发取号冲突时重试）；取最大版本号
        IndexModel([("rootId", ASCENDING), ("version", ASCENDING)], name="rootId_version_unique", unique=True),
        IndexModel([("ownerId", ASCENDING), ("updatedAt", DESCENDING)], name="ownerId_updatedAt"),
        IndexModel([("sharing.userIds", ASCENDING)], name="sharing_userIds"),
        IndexModel([("sharing.public", ASCENDING)], name="sharing_public",
                   partialFilterExpression={"sharing.public": True}),
        # 删除前检查有没有子版本、有没有版本恢复自它
        IndexModel([("parentId", ASCENDING)], name="parentId"),
        # 不用部分索引：查询 {restoredFrom: X} 时优化器无法推出它满足 {$type: objectId} 的过滤条件，不会使用部分索引
        IndexModel([("restoredFrom", ASCENDING)], name="restoredFrom"),
    ],
    QUESTION_BANKS: [
        IndexModel([("ownerId", ASCENDING), ("updatedAt", DESCENDING)], name="ownerId_updatedAt"),
        IndexModel([("sharing.userIds", ASCENDING)], name="sharing_userIds"),
        IndexModel([("sharing.public", ASCENDING)], name="sharing_public",
                   partialFilterExpression={"sharing.public": True}),
        # 某个版本在哪些题库中（删除版本前检查）
        IndexModel([("items.questionId", ASCENDING)], name="items_questionId"),
    ],
}


def ensure_schema(db: Database) -> None:
    """创建/更新所有集合的校验规则和索引（幂等）。"""
    existing = set(db.list_collection_names())
    for name, schema in SCHEMAS.items():
        validator = {"$jsonSchema": schema}
        if name in existing:
            db.command("collMod", name, validator=validator,
                       validationLevel="moderate", validationAction="error")
        else:
            db.create_collection(name, validator=validator,
                                 validationLevel="moderate", validationAction="error")
    for name, indexes in INDEXES.items():
        db[name].create_indexes(indexes)
