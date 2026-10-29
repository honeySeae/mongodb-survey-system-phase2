"""第二阶段第 11 步：第二阶段示例数据（scripts/seed_phase2.py，在测试库上运行）。

检查示例数据确实演示了每一项新功能，且统计数字与手工计算一致：
总体满意度：2025 秋（once，v1）6 份；2026 春（latest，v2）5 人最新答卷；2026 秋（all，v4）6 份。
合并：非常满意 4、满意 7、说不上好坏 2、不满意 2、很不满意 2（只在 v1 中）；答卷 17、作答人数 12。
学习时间（老师自己的三份问卷）：(16 + 21 + 23) / 16 = 3.75。
"""
from bson import ObjectId

from app.db import QUESTION_BANKS, QUESTIONS, RESPONSES, SURVEYS, USERS
from app.services import banks as bank_service
from app.services import cross_stats
from app.services import usage as usage_service
from scripts import seed_demo, seed_phase2


def uid(db, name):
    return db[USERS].find_one({"username": name})["_id"]


def test_versions_including_restore(db):
    result = seed_phase2.seed(db)
    assert result["created"] is True
    root = ObjectId(result["satisfaction_id"])
    versions = list(db[QUESTIONS].find({"rootId": root}).sort("version", 1))
    by_no = {v["version"]: v for v in versions}
    assert sorted(by_no) == [1, 2, 3, 4, 5]
    assert by_no[2]["parentId"] == by_no[1]["_id"] and by_no[3]["parentId"] == by_no[2]["_id"]
    assert by_no[4]["parentId"] == by_no[3]["_id"] and by_no[4]["restoredFrom"] == by_no[2]["_id"]   # 恢复 v2
    assert [o["text"] for o in by_no[4]["options"]] == [o["text"] for o in by_no[2]["options"]]
    assert by_no[5]["ownerId"] == uid(db, "demo_colleague")                                          # 同事的版本
    assert by_no[5]["sharing"] == {"public": False, "userIds": []}
    # 用过的版本锁定，试改的 v3 没有用过
    assert [by_no[n].get("lockedAt") is not None for n in (1, 2, 3, 4, 5)] == [True, True, False, True, True]


def test_surveys_policies_and_responses(db):
    seed_phase2.seed(db)
    teacher = uid(db, "demo_teacher")
    surveys = {s["shortCode"]: s for s in db[SURVEYS].find({"ownerId": teacher})}
    assert {c: (s["status"], s["settings"]["submissionPolicy"]) for c, s in surveys.items()} == {
        "Db25Fa": ("published", "once"), "Db26Sp": ("published", "latest"), "Db26Fa": ("published", "all")}
    counts = {c: db[RESPONSES].count_documents({"surveyId": s["_id"]}) for c, s in surveys.items()}
    assert counts == {"Db25Fa": 6, "Db26Sp": 6, "Db26Fa": 6}
    # 2025 秋“建议”是问卷中直接建的、发布后存入我的题目
    advice = next(q for q in surveys["Db25Fa"]["questions"] if q["type"] == "text")
    assert advice["source"]["version"] == 1
    # 2026 秋保留跳转规则：不满意 → 建议
    sat = surveys["Db26Fa"]["questions"][0]
    assert sat["logic"]["rules"][0]["goto"] == surveys["Db26Fa"]["questions"][3]["id"]


def test_cross_survey_stats_numbers(db):
    result = seed_phase2.seed(db)
    teacher = uid(db, "demo_teacher")
    r = cross_stats.cross_stats(db, teacher, result["satisfaction_id"], version_ids=None)
    o = r["overall"]
    assert (o["survey_count"], o["answer_count"], o["respondent_count"]) == (3, 17, 12)
    assert [(x["text"], x["count"], x["only_in_old_versions"]) for x in o["options"]] == [
        ("非常满意", 4, False), ("满意", 7, False), ("说不上好坏", 2, False), ("不满意", 2, False),
        ("很不满意", 2, True)]
    # 同事的助教课问卷不计入老师的统计
    assert sorted(s["survey"]["shortCode"] for s in r["surveys"]) == ["Db25Fa", "Db26Fa", "Db26Sp"]

    hours = cross_stats.cross_stats(db, teacher, result["hours_id"], version_ids=None)["overall"]
    assert hours["answer_count"] == 16 and hours["average"] == 3.75


def test_sharing_bank_and_usage(db):
    result = seed_phase2.seed(db)
    teacher, colleague = uid(db, "demo_teacher"), uid(db, "demo_colleague")
    bank = db[QUESTION_BANKS].find_one({"_id": ObjectId(result["bank_id"])})
    assert bank["sharing"]["userIds"] == [colleague] and len(bank["items"]) == 5
    resolved = bank_service.resolve_items(db, bank, teacher)
    notices = [r.notice for r in resolved]
    assert notices[0] == "有新版本 v4 可换"                 # 满意度在题库中是 v2
    assert notices[2] == "有新版本 v2 可换"                 # 教学环节在题库中是 v1
    assert "原作者 demo_colleague 已取消共享" in notices[4]   # 你的专业：同事取消了共享
    assert resolved[4].version is None
    # 同事看到的题库：不可用，但没有原因
    assert [r.notice for r in bank_service.resolve_items(db, bank, colleague)] == [None] * 5

    usage = usage_service.usage(db, teacher, result["satisfaction_id"], "question")
    assert len(usage["mine"]) == 3 and usage["others_count"] == 1      # 同事的助教课问卷只计数
    hours_usage = usage_service.usage(db, teacher, result["hours_id"], "version")
    assert len(hours_usage["mine"]) == 3 and hours_usage["others_count"] == 1   # 同事通过题库使用


def test_idempotent_and_reset(db):
    first = seed_phase2.seed(db)
    again = seed_phase2.seed(db)
    assert again["created"] is False and again["satisfaction_id"] == first["satisfaction_id"]
    assert db[SURVEYS].count_documents({"shortCode": "Db25Fa"}) == 1
    reset = seed_phase2.seed(db, reset=True)
    assert reset["created"] is True and reset["satisfaction_id"] != first["satisfaction_id"]
    assert db[SURVEYS].count_documents({"shortCode": {"$in": ["Db25Fa", "Db26Sp", "Db26Fa", "DbTa26"]}}) == 4


def test_phase1_demo_unaffected(db):
    """第一阶段示例数据与第二阶段示例数据可以同时存在，互不影响。"""
    p1 = seed_demo.seed(db)
    seed_phase2.seed(db)
    assert db[RESPONSES].count_documents({"surveyId": ObjectId(p1["survey_id"])}) == 13
    assert all("source" not in q for q in db[SURVEYS].find_one({"shortCode": "Food26"})["questions"])
