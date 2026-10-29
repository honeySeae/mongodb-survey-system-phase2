"""第二阶段第 9 步：单题跨问卷统计（设计文档 10.8，需求八）。

- 只统计自己的已发布、已关闭问卷；默认合并整道题的所有版本，可按版本筛选
- 每份问卷按自己的提交策略选答卷；不显示填写人
- 合并后的总体数据 + 每份问卷各自的数据；每份问卷的数据与第一阶段单份问卷统计一致
"""
import pytest
from bson import ObjectId

from app.stats.cross_pipelines import Target, cross_question_pipeline
from tests.builders import build_fruit_survey
from tests.conftest import auth_headers_for
from tests.test_fill import submit
from tests.test_question_library import GENDER, create, derive, ok
from tests.test_question_sharing import share
from tests.test_save_to_library import save
from tests.test_survey_library import add_lib, new_survey


def cross(client, headers, qid, **params):
    return client.get(f"/api/questions/{qid}/stats", params=params, headers=headers)


def publish_with(client, headers, qid, title, **settings):
    """建一份只有这道题的问卷并发布，返回 (问卷, 问卷中的题目)。"""
    s = new_survey(client, headers, title=title, **settings)
    q = ok(add_lib(client, headers, s["id"], qid, required=True), 201)["questions"][0]
    s = ok(client.post(f"/api/surveys/{s['id']}/publish", headers=headers))
    return s, q


def answer(client, headers, survey, q, value):
    ok(submit(client, headers, survey["shortCode"], {q["id"]: value}), 201)


def by_text(options):
    return {o["text"]: o["count"] for o in options}


@pytest.fixture
def carol(client):
    return auth_headers_for(client, "carol")


# ---------- 单选：合并不同版本 ----------
@pytest.fixture
def gender(client, alice, bob, carol):
    """S1 用 v1（男、女，once）；S2 用 v2（女 改为 女性、新增 其他，all）。"""
    v1 = create(client, alice, GENDER)
    male, female = v1["options"]
    v2 = ok(derive(client, alice, v1["id"], options=[
        male, {"id": female["id"], "text": "女性"}, {"text": "其他"}]), 201)
    s1, q1 = publish_with(client, alice, v1["id"], "S1")
    s2, q2 = publish_with(client, alice, v2["id"], "S2", submissionPolicy="all")
    answer(client, bob, s1, q1, male["id"])
    answer(client, carol, s1, q1, female["id"])
    answer(client, bob, s2, q2, female["id"])
    answer(client, bob, s2, q2, female["id"])          # all：同一人两次都算
    answer(client, carol, s2, q2, v2["options"][2]["id"])
    return {"v1": v1, "v2": v2, "s1": s1, "s2": s2, "q1": q1, "q2": q2}


def test_merge_versions_by_option_id(client, alice, gender):
    r = ok(cross(client, alice, gender["v1"]["id"]))
    assert r["type"] == "single_choice" and r["versionFilter"] is None
    o = r["overall"]
    assert (o["surveyCount"], o["answerCount"], o["respondentCount"]) == (2, 5, 2)   # bob、carol 跨问卷去重
    # 选项按 id 合并，文字取版本号最大的版本（“女” → “女性”）
    assert [(x["text"], x["count"]) for x in o["options"]] == [("男", 1), ("女性", 3), ("其他", 1)]
    assert r["title"] == "性别"
    per = {s["title"]: s for s in r["surveys"]}
    assert (per["S1"]["version"], per["S1"]["answerCount"], per["S1"]["respondentCount"]) == (1, 2, 2)
    assert by_text(per["S1"]["options"]) == {"男": 1, "女": 1}           # 每份问卷用它自己的选项文字
    assert (per["S2"]["version"], per["S2"]["answerCount"], per["S2"]["respondentCount"]) == (2, 3, 2)
    assert by_text(per["S2"]["options"]) == {"男": 0, "女性": 2, "其他": 1}
    assert per["S2"]["submissionPolicy"] == "all" and per["S2"]["url"].endswith(gender["s2"]["shortCode"])


def test_per_survey_numbers_match_single_survey_stats(client, alice, gender):
    """每份问卷各自的数据与第一阶段单份问卷统计完全一致（口径复用 scope_filter）。"""
    r = ok(cross(client, alice, gender["v2"]["id"]))
    for s in r["surveys"]:
        single = ok(client.get(f"/api/surveys/{s['surveyId']}/stats/questions/{s['surveyQuestionId']}",
                               headers=alice))["question"]
        assert (s["answerCount"], s["respondentCount"]) == (single["answerCount"], single["respondentCount"])
        assert s["options"] == [{k: o[k] for k in ("id", "text", "count")} for o in single["options"]]


def test_filter_by_version(client, alice, gender):
    r = ok(cross(client, alice, gender["v1"]["id"], versionId=gender["v1"]["id"]))
    assert r["versionFilter"] == [gender["v1"]["id"]]
    assert [s["title"] for s in r["surveys"]] == ["S1"]
    assert r["overall"]["answerCount"] == 2
    assert by_text(r["overall"]["options"]) == {"男": 1, "女": 1}       # 只有 v1 时文字取 v1 的
    both = ok(cross(client, alice, gender["v1"]["id"], versionId=[gender["v1"]["id"], gender["v2"]["id"]]))
    assert both["overall"]["answerCount"] == 5


def test_version_filter_validation(client, alice, gender):
    other = create(client, alice)
    r = cross(client, alice, gender["v1"]["id"], versionId=other["id"])   # 另一道题的版本
    assert r.status_code == 422
    assert cross(client, alice, gender["v1"]["id"], versionId="bad").status_code == 422
    assert cross(client, alice, gender["v1"]["id"], versionId=str(ObjectId())).status_code == 422


def test_latest_policy(client, alice, bob):
    v1 = create(client, alice, GENDER)
    male, female = v1["options"]
    s, q = publish_with(client, alice, v1["id"], "可以重填", submissionPolicy="latest")
    answer(client, bob, s, q, male["id"])
    answer(client, bob, s, q, female["id"])            # latest：只算最后一次
    o = ok(cross(client, alice, v1["id"]))["overall"]
    assert (o["answerCount"], o["respondentCount"]) == (1, 1)
    assert by_text(o["options"]) == {"男": 0, "女": 1}


# ---------- 哪些问卷参与统计 ----------
def test_only_my_published_or_closed_surveys(client, alice, bob, carol):
    v1 = create(client, alice, GENDER)
    male = v1["options"][0]["id"]
    ok(share(client, alice, v1["id"], ["bob"]))
    mine, q = publish_with(client, alice, v1["id"], "alice 已发布")
    closed, qc = publish_with(client, alice, v1["id"], "alice 已关闭")
    answer(client, carol, mine, q, male)
    answer(client, carol, closed, qc, male)
    ok(client.post(f"/api/surveys/{closed['id']}/close", headers=alice))
    draft = new_survey(client, alice, title="alice 草稿")
    ok(add_lib(client, alice, draft["id"], v1["id"]), 201)
    bobs, qb = publish_with(client, bob, v1["id"], "bob 的问卷")     # 别人的问卷不计入
    answer(client, carol, bobs, qb, male)

    r = ok(cross(client, alice, v1["id"]))
    assert {s["title"] for s in r["surveys"]} == {"alice 已发布", "alice 已关闭"}
    assert r["overall"]["answerCount"] == 2
    # bob（被共享）只统计他自己的问卷
    rb = ok(cross(client, bob, v1["id"]))
    assert [s["title"] for s in rb["surveys"]] == ["bob 的问卷"] and rb["overall"]["answerCount"] == 1


def test_permissions_and_empty(client, alice, bob):
    v1 = create(client, alice)
    assert cross(client, bob, v1["id"]).status_code == 404
    assert client.get(f"/api/questions/{v1['id']}/stats").status_code == 401
    r = ok(cross(client, alice, v1["id"]))           # 还没有问卷使用：0 和空列表，不报错
    assert r["surveys"] == [] and r["overall"] == {
        "surveyCount": 0, "answerCount": 0, "respondentCount": 0, "options": None,
        "average": None, "items": [], "itemsTotal": 0}


# ---------- 数字、文本、多选 ----------
def test_number_average_and_items(client, alice, bob, carol):
    v1 = create(client, alice)
    v2 = ok(derive(client, alice, v1["id"], title="你的年龄（周岁）"), 201)
    s1, q1 = publish_with(client, alice, v1["id"], "去年")
    s2, q2 = publish_with(client, alice, v2["id"], "今年")
    answer(client, bob, s1, q1, 10)
    answer(client, carol, s1, q1, 20)
    answer(client, bob, s2, q2, 60)
    r = ok(cross(client, alice, v1["id"]))
    o = r["overall"]
    assert o["average"] == 30                     # (10 + 20 + 60) / 3，按全部答案计算，不是 (15 + 60) / 2
    assert {s["title"]: s["average"] for s in r["surveys"]} == {"去年": 15, "今年": 60}
    assert r["title"] == "你的年龄（周岁）"           # 版本号最大的版本的题目文字
    assert o["itemsTotal"] == 3
    assert [(i["surveyTitle"], i["value"]) for i in o["items"]] == [("今年", 60), ("去年", 20), ("去年", 10)]
    page = ok(cross(client, alice, v1["id"], offset=1, limit=1))["overall"]["items"]
    assert [i["value"] for i in page] == [20]
    assert cross(client, alice, v1["id"], limit=201).status_code == 422


def test_text_items(client, alice, bob):
    v1 = create(client, alice, {"type": "text", "title": "建议", "validation": {"maxLength": 100}})
    s1, q1 = publish_with(client, alice, v1["id"], "A")
    s2, q2 = publish_with(client, alice, v1["id"], "B")
    answer(client, bob, s1, q1, "多开课")
    answer(client, bob, s2, q2, "少作业")
    o = ok(cross(client, alice, v1["id"]))["overall"]
    assert [(i["surveyTitle"], i["value"]) for i in o["items"]] == [("B", "少作业"), ("A", "多开课")]
    assert o["respondentCount"] == 1 and o["answerCount"] == 2 and o["average"] is None


def test_multiple_choice(client, alice, bob, carol):
    v1 = create(client, alice, {"type": "multiple_choice", "title": "爱好",
                                "options": [{"text": "读书"}, {"text": "运动"}, {"text": "音乐"}]})
    read, sport, music = (o["id"] for o in v1["options"])
    s1, q1 = publish_with(client, alice, v1["id"], "A")
    s2, q2 = publish_with(client, alice, v1["id"], "B")
    answer(client, bob, s1, q1, [read, sport])
    answer(client, carol, s2, q2, [sport, music])
    o = ok(cross(client, alice, v1["id"]))["overall"]
    assert by_text(o["options"]) == {"读书": 1, "运动": 2, "音乐": 1}
    assert o["answerCount"] == 2                  # 多选按答卷计数，不按选项数


# ---------- 不显示填写人 ----------
def test_no_respondent_info(client, alice, bob, gender):
    """无论问卷是否匿名，结果中都没有填写人（gender 夹具中的问卷都不是匿名问卷）。"""
    text = str(ok(cross(client, alice, gender["v1"]["id"])))
    assert "bob" not in text and "carol" not in text
    assert "respondent" not in text.replace("respondentCount", "")      # 只有人数，没有填写人


def test_pipeline_has_no_lookup_or_respondent_output():
    targets = [Target(ObjectId(), "q_aaaaaa", {}), Target(ObjectId(), "q_bbbbbb", {"isLatest": True})]
    for qtype in ("single_choice", "multiple_choice", "text", "number"):
        pipeline = cross_question_pipeline(targets, qtype)
        text = str(pipeline)
        assert "$lookup" not in text
        facet = pipeline[-1]["$facet"]
        for stages in facet.values():
            for stage in stages:
                assert "respondentId" not in stage.get("$project", {})
        # 前三步：每份问卷用自己的口径，只保留各自这道题的答案
        assert pipeline[0] == {"$match": {"$or": [
            {"surveyId": targets[0].survey_id, "answers.questionId": "q_aaaaaa"},
            {"surveyId": targets[1].survey_id, "isLatest": True, "answers.questionId": "q_bbbbbb"}]}}
        assert pipeline[1] == {"$unwind": "$answers"}
        assert pipeline[2] == {"$match": {"$or": [
            {"surveyId": targets[0].survey_id, "answers.questionId": "q_aaaaaa"},
            {"surveyId": targets[1].survey_id, "answers.questionId": "q_bbbbbb"}]}}


def test_first_stage_uses_index(client, alice, db, gender):
    from app.db import RESPONSES
    targets = [Target(ObjectId(gender["s1"]["id"]), gender["q1"]["id"], {}),
               Target(ObjectId(gender["s2"]["id"]), gender["q2"]["id"], {})]
    plan = db.command("explain", {"aggregate": RESPONSES, "pipeline": cross_question_pipeline(targets, "single_choice"),
                                  "cursor": {}}, verbosity="queryPlanner")
    assert "IXSCAN" in str(plan)


# ---------- 与第一阶段兼容 ----------
def test_phase1_answers_counted_after_saving_to_library(client, alice, bob):
    """第一阶段式问卷（问卷中直接建的题）收集的答卷：题存进题目库后计入跨问卷统计。"""
    built = build_fruit_survey(client, alice)
    q1 = built["q"][0]
    ok(submit(client, bob, built["survey"]["shortCode"],
              {q1["id"]: built["o"]["不喜欢"], built["q"][4]["id"]: "无"}), 201)
    v1 = ok(save(client, alice, built["survey"]["id"], q1["id"]), 201)["question"]
    s2, q2 = publish_with(client, alice, v1["id"], "新问卷")
    answer(client, bob, s2, q2, built["o"]["喜欢"])
    o = ok(cross(client, alice, v1["id"]))["overall"]
    assert by_text(o["options"]) == {"喜欢": 1, "不喜欢": 1}
    assert (o["surveyCount"], o["answerCount"], o["respondentCount"]) == (2, 2, 1)


# ---------- 只在旧版本中出现的选项 ----------
def test_option_deleted_in_newer_version_still_counted(client, alice, bob, carol):
    """v1：男、女、保密；v2：“保密”改为“不想说”；v3：删掉这个选项。
    用 v1、v2 的问卷里选了它的答案照常计数，总数正确；文字取含有它的最新版本（v2 的“不想说”），并标注只在旧版本中出现。"""
    v1 = create(client, alice, {**GENDER, "options": [{"text": "男"}, {"text": "女"}, {"text": "保密"}]})
    male, female, secret = v1["options"]
    v2 = ok(derive(client, alice, v1["id"], options=[male, female, {"id": secret["id"], "text": "不想说"}]), 201)
    v3 = ok(derive(client, alice, v2["id"], options=[male, female]), 201)
    s1, q1 = publish_with(client, alice, v1["id"], "v1 的问卷")
    s2, q2 = publish_with(client, alice, v2["id"], "v2 的问卷")
    s3, q3 = publish_with(client, alice, v3["id"], "v3 的问卷")
    answer(client, bob, s1, q1, secret["id"])
    answer(client, carol, s1, q1, male["id"])
    answer(client, bob, s2, q2, secret["id"])
    answer(client, bob, s3, q3, female["id"])

    o = ok(cross(client, alice, v1["id"]))["overall"]
    assert o["options"] == [
        {"id": male["id"], "text": "男", "count": 1, "onlyInOldVersions": False},
        {"id": female["id"], "text": "女", "count": 1, "onlyInOldVersions": False},
        {"id": secret["id"], "text": "不想说", "count": 2, "onlyInOldVersions": True},   # 排在最新版本的选项之后
    ]
    assert o["answerCount"] == 4 == sum(x["count"] for x in o["options"])    # 没有答案被丢掉
    # 每份问卷各自的数据用它自己的选项
    per = {s["title"]: by_text(s["options"]) for s in ok(cross(client, alice, v1["id"]))["surveys"]}
    assert per == {"v1 的问卷": {"男": 1, "女": 0, "保密": 1}, "v2 的问卷": {"男": 0, "女": 0, "不想说": 1},
                   "v3 的问卷": {"男": 0, "女": 1}}

    # “最新版本”指参与统计的版本中最新的：只统计 v1、v2 时，这个选项不算只在旧版本中出现
    o = ok(cross(client, alice, v1["id"], versionId=[v1["id"], v2["id"]]))["overall"]
    assert {x["text"]: x["onlyInOldVersions"] for x in o["options"]} == {"男": False, "女": False, "不想说": False}


def test_multiple_choice_option_deleted_in_newer_version(client, alice, bob):
    v1 = create(client, alice, {"type": "multiple_choice", "title": "爱好",
                                "options": [{"text": "读书"}, {"text": "游戏"}]})
    read, game = v1["options"]
    v2 = ok(derive(client, alice, v1["id"], options=[read, {"text": "运动"}]), 201)
    s1, q1 = publish_with(client, alice, v1["id"], "旧")
    s2, q2 = publish_with(client, alice, v2["id"], "新")
    answer(client, bob, s1, q1, [read["id"], game["id"]])
    answer(client, bob, s2, q2, [read["id"], v2["options"][1]["id"]])
    o = ok(cross(client, alice, v1["id"]))["overall"]
    assert [(x["text"], x["count"], x["onlyInOldVersions"]) for x in o["options"]] == [
        ("读书", 2, False), ("运动", 1, False), ("游戏", 1, True)]
    assert o["answerCount"] == 2


# ---------- 按问卷筛选 ----------
def test_filter_by_survey(client, alice, bob, carol, gender):
    """比较“去年的问卷”和“今年的问卷”：只统计指定的问卷，默认全部。"""
    s1, s2 = gender["s1"]["id"], gender["s2"]["id"]
    v1 = gender["v1"]["id"]
    r = ok(cross(client, alice, v1, surveyId=s1))
    assert r["surveyFilter"] == [s1] and [s["title"] for s in r["surveys"]] == ["S1"]
    assert (r["overall"]["answerCount"], r["overall"]["respondentCount"]) == (2, 2)
    assert by_text(r["overall"]["options"]) == {"男": 1, "女": 1}   # 只有 v1 参与：文字取 v1 的
    r = ok(cross(client, alice, v1, surveyId=[s1, s2]))
    assert r["overall"]["answerCount"] == 5 and r["surveyFilter"] == sorted([s1, s2])
    assert ok(cross(client, alice, v1))["surveyFilter"] is None


def test_survey_filter_combined_with_version_filter(client, alice, gender):
    """同时按版本和问卷筛选时取交集：S1 用的是 v1，只要 v2 就没有问卷参与。"""
    r = ok(cross(client, alice, gender["v1"]["id"], surveyId=gender["s1"]["id"], versionId=gender["v2"]["id"]))
    assert r["surveys"] == [] and r["overall"]["surveyCount"] == 0 and r["overall"]["answerCount"] == 0


def test_survey_filter_validation(client, alice, bob, gender):
    v1 = gender["v1"]["id"]
    draft = new_survey(client, alice, title="草稿")
    ok(add_lib(client, alice, draft["id"], gender["v2"]["id"]), 201)
    unrelated = build_fruit_survey(client, alice)["survey"]["id"]       # 没有用这道题
    ok(share(client, alice, v1, ["bob"]))
    bobs, _ = publish_with(client, bob, v1, "bob 的问卷")                 # 别人的问卷
    for bad in (draft["id"], unrelated, bobs["id"], "not-an-id", str(ObjectId())):
        r = cross(client, alice, v1, surveyId=[gender["s1"]["id"], bad])
        assert r.status_code == 422, bad
        assert r.json()["errors"][0]["field"] == "surveyId[1]"
