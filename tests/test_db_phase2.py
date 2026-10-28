"""第二阶段第 2 步：新集合 questions、questionBanks 的 $jsonSchema 校验与索引，
以及 surveys.questions[].source（设计文档 10.2、10.3、10.7、10.10）。

同时验证与第一阶段兼容：没有 source 的旧问卷照常写入、更新。
"""
from datetime import datetime, timezone

import pytest
from bson import ObjectId
from pymongo.errors import DuplicateKeyError, WriteError

from app.db import QUESTION_BANKS, QUESTIONS, SURVEYS
from app.db_schema import ensure_schema
from tests.test_db import make_survey


def now():
    return datetime.now(timezone.utc)


def make_question(**overrides):
    qid = ObjectId()
    doc = {
        "_id": qid, "rootId": qid, "parentId": None, "version": 1, "ownerId": ObjectId(),
        "type": "number", "title": "你的年龄",
        "validation": {"min": 0, "max": 150, "integerOnly": True},
        "sharing": {"public": False, "userIds": []},
        "lockedAt": None, "createdAt": now(), "updatedAt": now(),
    }
    doc.update(overrides)
    return doc


def make_bank(**overrides):
    doc = {
        "ownerId": ObjectId(), "name": "学生基本信息", "description": "",
        "items": [{"questionId": ObjectId(), "rootId": ObjectId(), "addedAt": now()}],
        "sharing": {"public": True, "userIds": []},
        "createdAt": now(), "updatedAt": now(),
    }
    doc.update(overrides)
    return doc


def survey_with_source(source):
    survey = make_survey()
    survey["questions"][0]["source"] = source
    return survey


# ---------- 集合与校验规则 ----------
def test_new_collections_created_with_validator(db):
    infos = {c["name"]: c for c in db.list_collections()}
    for name in (QUESTIONS, QUESTION_BANKS):
        assert name in infos
        options = infos[name]["options"]
        assert "$jsonSchema" in options["validator"]
        assert options["validationLevel"] == "moderate"
        assert options["validationAction"] == "error"


def test_ensure_schema_is_idempotent_for_new_collections(db):
    names = (SURVEYS, QUESTIONS, QUESTION_BANKS)
    before = {n: sorted(db[n].index_information()) for n in names}
    ensure_schema(db)
    ensure_schema(db)
    assert {n: sorted(db[n].index_information()) for n in names} == before


def test_valid_phase2_documents_accepted(db):
    v1 = make_question()
    db[QUESTIONS].insert_one(v1)
    # 派生版本、恢复版本、选择题、带共享用户
    db[QUESTIONS].insert_one(make_question(
        rootId=v1["_id"], parentId=v1["_id"], version=2, title="你的年龄（周岁）"))
    db[QUESTIONS].insert_one(make_question(
        rootId=v1["_id"], parentId=v1["_id"], restoredFrom=v1["_id"], version=3, lockedAt=now()))
    db[QUESTIONS].insert_one(make_question(
        type="single_choice", title="性别",
        options=[{"id": "o_aaa111", "text": "男"}, {"id": "o_bbb222", "text": "女"}],
        validation={}, sharing={"public": False, "userIds": [ObjectId()]}))
    db[QUESTION_BANKS].insert_one(make_bank())
    db[QUESTION_BANKS].insert_one(make_bank(items=[], description="空题库"))
    db[SURVEYS].insert_one(survey_with_source(
        {"questionId": v1["_id"], "rootId": v1["_id"], "version": 1}))


@pytest.mark.parametrize(
    "collection, doc",
    [
        (QUESTIONS, make_question(validation={"required": True, "min": 0})),     # 题目版本不存 required
        (QUESTIONS, make_question(type="rating")),                               # 非法题型
        (QUESTIONS, make_question(version=0)),                                   # 版本号从 1 开始
        (QUESTIONS, make_question(rootId="A1")),                                 # rootId 类型错误
        (QUESTIONS, make_question(parentId="A1")),                               # parentId 类型错误
        (QUESTIONS, make_question(title="")),                                    # 空标题
        (QUESTIONS, make_question(sharing={"public": True})),                    # 缺 userIds
        (QUESTIONS, make_question(sharing={"public": False, "userIds": ["bob"]})),  # 存用户名而不是 id
        (QUESTIONS, make_question(lockedAt="2026-10-28")),                       # 时间存成字符串
        (QUESTIONS, {k: v for k, v in make_question().items() if k != "sharing"}),  # 缺 sharing
        (QUESTION_BANKS, make_bank(name="")),                                    # 空名称
        (QUESTION_BANKS, {k: v for k, v in make_bank().items() if k != "items"}),  # 缺 items
        (QUESTION_BANKS, make_bank(items=[{"questionId": ObjectId(), "addedAt": now()}])),  # 条目缺 rootId
        (QUESTION_BANKS, make_bank(sharing={"public": "yes", "userIds": []})),   # public 类型错误
        (SURVEYS, survey_with_source({"questionId": ObjectId(), "version": 1})),  # source 缺 rootId
        (SURVEYS, survey_with_source({"questionId": "A1", "rootId": ObjectId(), "version": 1})),  # 类型错误
        (SURVEYS, survey_with_source({"questionId": ObjectId(), "rootId": ObjectId(), "version": 0})),
    ],
)
def test_invalid_phase2_documents_rejected(db, collection, doc):
    with pytest.raises(WriteError) as exc:
        db[collection].insert_one(doc)
    assert exc.value.code == 121  # DocumentValidationFailure


# ---------- 与第一阶段兼容 ----------
def test_phase1_survey_without_source_still_valid(db):
    """第一阶段格式的问卷（题目没有 source）照常写入和更新。"""
    sid = db[SURVEYS].insert_one(make_survey()).inserted_id
    db[SURVEYS].update_one({"_id": sid}, {"$set": {"title": "改个标题", "updatedAt": now()}})
    assert "source" not in db[SURVEYS].find_one({"_id": sid})["questions"][0]


def test_ensure_schema_on_existing_phase1_data(db):
    """在已有第一阶段数据的库上重新执行初始化（模拟部署第二阶段），旧问卷不受影响、可以继续更新。"""
    sid = db[SURVEYS].insert_one(make_survey(shortCode="old001")).inserted_id
    ensure_schema(db)
    result = db[SURVEYS].update_one({"_id": sid}, {"$set": {"status": "published"}})
    assert result.modified_count == 1


# ---------- 索引 ----------
def test_phase2_indexes_match_design(db):
    questions = db[QUESTIONS].index_information()
    assert questions["rootId_version_unique"]["key"] == [("rootId", 1), ("version", 1)]
    assert questions["rootId_version_unique"]["unique"] is True
    assert questions["ownerId_updatedAt"]["key"] == [("ownerId", 1), ("updatedAt", -1)]
    assert questions["sharing_userIds"]["key"] == [("sharing.userIds", 1)]
    assert questions["sharing_public"]["key"] == [("sharing.public", 1)]
    assert questions["sharing_public"]["partialFilterExpression"] == {"sharing.public": True}
    assert questions["parentId"]["key"] == [("parentId", 1)]
    assert questions["restoredFrom"]["key"] == [("restoredFrom", 1)]

    banks = db[QUESTION_BANKS].index_information()
    assert banks["ownerId_updatedAt"]["key"] == [("ownerId", 1), ("updatedAt", -1)]
    assert banks["sharing_userIds"]["key"] == [("sharing.userIds", 1)]
    assert banks["sharing_public"]["partialFilterExpression"] == {"sharing.public": True}
    assert banks["items_questionId"]["key"] == [("items.questionId", 1)]

    surveys = db[SURVEYS].index_information()
    assert surveys["questions_source_questionId"]["key"] == [("questions.source.questionId", 1)]
    assert surveys["questions_source_rootId_ownerId"]["key"] == [
        ("questions.source.rootId", 1), ("ownerId", 1)]


def test_version_number_unique_within_question(db):
    """同一道题内版本号不重复（10.4 第 1 条：并发取号冲突时由索引拦截、重试）。"""
    v1 = make_question()
    db[QUESTIONS].insert_one(v1)
    db[QUESTIONS].insert_one(make_question(rootId=v1["_id"], parentId=v1["_id"], version=2))
    with pytest.raises(DuplicateKeyError):
        db[QUESTIONS].insert_one(make_question(rootId=v1["_id"], parentId=v1["_id"], version=2))


def test_same_version_number_allowed_in_different_questions(db):
    db[QUESTIONS].insert_one(make_question())
    db[QUESTIONS].insert_one(make_question())
    assert db[QUESTIONS].count_documents({"version": 1}) == 2


def _winning_plan(cursor) -> str:
    return str(cursor.explain()["queryPlanner"]["winningPlan"])


def test_usage_queries_use_indexes(db):
    """“被哪些问卷使用”、跨问卷统计找问卷、删除前检查都能用到索引。"""
    v1 = make_question()
    db[QUESTIONS].insert_one(v1)
    db[SURVEYS].insert_one(survey_with_source(
        {"questionId": v1["_id"], "rootId": v1["_id"], "version": 1}))
    db[SURVEYS].insert_one(make_survey(shortCode="old002"))  # 第一阶段的问卷，没有 source

    assert "questions_source_questionId" in _winning_plan(
        db[SURVEYS].find({"questions.source.questionId": v1["_id"]}))
    assert "questions_source_rootId_ownerId" in _winning_plan(
        db[SURVEYS].find({"questions.source.rootId": v1["_id"], "ownerId": ObjectId()}))
    # 字段名也会出现在全表扫描的 filter 中，这里按索引名精确匹配
    assert "'indexName': 'restoredFrom'" in _winning_plan(db[QUESTIONS].find({"restoredFrom": v1["_id"]}))
    assert "'indexName': 'parentId'" in _winning_plan(db[QUESTIONS].find({"parentId": v1["_id"]}))
    assert "items_questionId" in _winning_plan(db[QUESTION_BANKS].find({"items.questionId": v1["_id"]}))
    assert "sharing_public" in _winning_plan(db[QUESTIONS].find({"sharing.public": True}))
