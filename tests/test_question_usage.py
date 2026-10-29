"""第二阶段第 8 步：查看题目被哪些问卷使用（设计文档 10.8，需求六）。

- 自己的问卷显示标题、状态、链接；别人的问卷只显示数量
- 按版本（scope=version）或按整道题（scope=question）查询
- 能访问这个版本的人都可以查；只依据问卷题目的 source
"""
from datetime import timedelta

from bson import ObjectId

from app.config import get_settings
from app.db import SURVEYS
from app.utils import now_utc
from tests.builders import build_fruit_survey
from tests.test_banks import add_item, new_bank, share_bank
from tests.test_question_library import GENDER, create, derive, ok
from tests.test_question_sharing import share
from tests.test_save_to_library import save
from tests.test_survey_library import add_lib, new_survey


def usage(client, headers, qid, scope=None):
    params = {"scope": scope} if scope else {}
    return client.get(f"/api/questions/{qid}/usage", params=params, headers=headers)


def test_unused_question(client, alice):
    v1 = create(client, alice)
    u = ok(usage(client, alice, v1["id"]))
    assert u == {"scope": "version", "questionId": v1["id"], "rootId": v1["rootId"], "mine": [],
                 "mineCount": 0, "othersCount": 0, "totalCount": 0}


def test_my_surveys_show_title_status_link(client, alice):
    v1 = create(client, alice)
    s = new_survey(client, alice, title="去年的调查")
    q = ok(add_lib(client, alice, s["id"], v1["id"]), 201)["questions"][0]
    ok(client.post(f"/api/surveys/{s['id']}/publish", headers=alice))
    u = ok(usage(client, alice, v1["id"]))
    assert u["mineCount"] == 1 and u["othersCount"] == 0
    entry = u["mine"][0]
    assert entry == {
        "id": s["id"], "title": "去年的调查", "status": "published", "isExpired": False,
        "shortCode": s["shortCode"], "url": f"{get_settings().public_base_url}/survey/{s['shortCode']}",
        "surveyQuestionId": q["id"], "questionId": v1["id"], "version": 1}


def test_version_scope_vs_question_scope(client, alice):
    """A 问卷用 v1，B 问卷用 v2：按版本只看到各自的问卷，按整道题看到两份。"""
    v1 = create(client, alice)
    v2 = ok(derive(client, alice, v1["id"], title="v2"), 201)
    a = new_survey(client, alice, title="A")["id"]
    b = new_survey(client, alice, title="B")["id"]
    ok(add_lib(client, alice, a, v1["id"]), 201)
    ok(add_lib(client, alice, b, v2["id"]), 201)

    assert [m["title"] for m in ok(usage(client, alice, v1["id"], "version"))["mine"]] == ["A"]
    assert [m["title"] for m in ok(usage(client, alice, v2["id"], "version"))["mine"]] == ["B"]
    whole = ok(usage(client, alice, v1["id"], "question"))
    assert whole["scope"] == "question"
    assert {(m["title"], m["version"]) for m in whole["mine"]} == {("A", 1), ("B", 2)}
    # 从任一版本查整道题，结果相同
    assert ok(usage(client, alice, v2["id"], "question"))["mine"] == whole["mine"]
    assert usage(client, alice, v1["id"], "everything").status_code == 422


def test_others_surveys_only_counted(client, alice, bob):
    v1 = create(client, alice)
    ok(share(client, alice, v1["id"], ["bob"]))
    mine = new_survey(client, alice, title="alice 的问卷")["id"]
    ok(add_lib(client, alice, mine, v1["id"]), 201)
    for title in ("bob 的问卷 1", "bob 的问卷 2"):
        ok(add_lib(client, bob, new_survey(client, bob, title=title)["id"], v1["id"]), 201)

    u = ok(usage(client, alice, v1["id"]))
    assert [m["title"] for m in u["mine"]] == ["alice 的问卷"]
    assert (u["othersCount"], u["totalCount"]) == (2, 3)
    # 被共享的人查询：只看到自己的问卷详情，所有者的问卷只计数
    ub = ok(usage(client, bob, v1["id"]))
    assert {m["title"] for m in ub["mine"]} == {"bob 的问卷 1", "bob 的问卷 2"}
    assert ub["othersCount"] == 1
    assert "alice 的问卷" not in str(ub)


def test_question_scope_includes_others_versions(client, alice, bob):
    """按整道题查询时包括别人派生的版本被使用的情况（别人的问卷仍只计数）。"""
    v1 = create(client, alice)
    ok(share(client, alice, v1["id"], ["bob"]))
    b2 = ok(derive(client, bob, v1["id"], title="bob 的版本"), 201)
    ok(add_lib(client, bob, new_survey(client, bob)["id"], b2["id"]), 201)
    assert ok(usage(client, alice, v1["id"], "version"))["totalCount"] == 0
    assert ok(usage(client, alice, v1["id"], "question"))["othersCount"] == 1


def test_permissions(client, alice, bob):
    v1 = create(client, alice)
    assert usage(client, bob, v1["id"]).status_code == 404        # 无权访问：与不存在一样
    assert usage(client, alice, "not-an-id").status_code == 404
    assert client.get(f"/api/questions/{v1['id']}/usage").status_code == 401
    # 通过共享的题库访问也可以查
    b = new_bank(client, alice)
    ok(add_item(client, alice, b["id"], v1["id"]), 201)
    ok(share_bank(client, alice, b["id"], ["bob"]))
    assert ok(usage(client, bob, v1["id"]))["totalCount"] == 0


def test_all_statuses_and_removed_questions(client, alice):
    """草稿、已发布、已关闭都算使用；题目从问卷中删除后不再计入（版本仍锁定）；
    问卷中直接建的题（没有 source）不算使用。"""
    v1 = create(client, alice, GENDER)
    draft, pub, closed, removed = (new_survey(client, alice, title=t)["id"]
                                   for t in ("草稿", "已发布", "已关闭", "删掉了"))
    for sid in (draft, pub, closed, removed):
        ok(add_lib(client, alice, sid, v1["id"]), 201)
    ok(client.post(f"/api/surveys/{pub}/publish", headers=alice))
    ok(client.post(f"/api/surveys/{closed}/publish", headers=alice))
    ok(client.post(f"/api/surveys/{closed}/close", headers=alice))
    q = ok(client.get(f"/api/surveys/{removed}", headers=alice))["questions"][0]
    ok(client.delete(f"/api/surveys/{removed}/questions/{q['id']}", headers=alice))
    build_fruit_survey(client, alice)                               # 没有 source 的问卷

    u = ok(usage(client, alice, v1["id"]))
    assert {(m["title"], m["status"]) for m in u["mine"]} == {
        ("草稿", "draft"), ("已发布", "published"), ("已关闭", "closed")}
    assert ok(client.get(f"/api/questions/{v1['id']}", headers=alice))["locked"] is True


def test_saved_from_survey_counts_as_usage(client, alice):
    """问卷中的题存进题目库后，原问卷就是这个版本的使用者（包括已发布的第一阶段式问卷）。"""
    built = build_fruit_survey(client, alice)
    v1 = ok(save(client, alice, built["survey"]["id"], built["q"][0]["id"]), 201)["question"]
    u = ok(usage(client, alice, v1["id"]))
    assert [(m["title"], m["status"], m["surveyQuestionId"]) for m in u["mine"]] == [
        ("水果偏好调查", "published", built["q"][0]["id"])]


def test_expired_flag(client, alice, db):
    v1 = create(client, alice)
    sid = new_survey(client, alice)["id"]
    ok(add_lib(client, alice, sid, v1["id"]), 201)
    db[SURVEYS].update_one({"_id": ObjectId(sid)},
                           {"$set": {"status": "published", "settings.deadline": now_utc() - timedelta(days=1)}})
    assert ok(usage(client, alice, v1["id"]))["mine"][0]["isExpired"] is True
