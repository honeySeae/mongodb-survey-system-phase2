"""第二阶段第 5 步：问卷使用题目库中的题（设计文档 10.3、10.4 第 2 条、10.5）。

- 从题目库添加：复制快照、记录 source、版本加锁；同一道题在一份问卷中只能出现一次；选项 id 冲突拒绝
- 来自题目库的题只能改是否必答和跳转规则；在草稿中可以换成同一道题的其他版本
- 填写、跳转、校验、统计对有 source 的题照常工作；填写者看不到 source
- 没有 source 的题行为与第一阶段相同（第一阶段的全部测试不改动、保持通过；这里另测混合问卷）
"""
from bson import ObjectId

from app.db import QUESTIONS, SURVEYS
from tests.builders import as_update
from tests.test_fill import get, submit
from tests.test_question_library import AGE, GENDER, create, derive, ok
from tests.test_question_sharing import share


def new_survey(client, headers, **settings):
    return ok(client.post("/api/surveys", json={"title": "年度调查", **settings}, headers=headers), 201)


def add_lib(client, headers, sid, qid, **body):
    return client.post(f"/api/surveys/{sid}/questions/from-library",
                       json={"questionId": qid, **body}, headers=headers)


def add_direct(client, headers, sid, **q):
    return ok(client.post(f"/api/surveys/{sid}/questions", json=q, headers=headers), 201)


def update(client, headers, sid, q, **changes):
    return client.put(f"/api/surveys/{sid}/questions/{q['id']}", json=as_update(q, **changes), headers=headers)


def switch(client, headers, sid, survey_qid, version_id):
    return client.put(f"/api/surveys/{sid}/questions/{survey_qid}/version",
                      json={"questionId": version_id}, headers=headers)


def locked(client, headers, qid) -> bool:
    return ok(client.get(f"/api/questions/{qid}", headers=headers))["locked"]


# ---------- 从题目库添加 ----------
def test_add_from_library_copies_snapshot(client, alice, db):
    v1 = create(client, alice, GENDER)
    sid = new_survey(client, alice)["id"]
    s = ok(add_lib(client, alice, sid, v1["id"], required=True), 201)
    q = s["questions"][0]
    assert q["type"] == "single_choice" and q["title"] == "性别"
    assert q["options"] == v1["options"]                          # 选项 id 沿用来源版本
    assert q["validation"] == {"required": True}                  # 是否必答由问卷决定
    assert q["source"] == {"questionId": v1["id"], "rootId": v1["rootId"], "version": 1}
    assert q["id"].startswith("q_") and q["id"] != v1["id"]       # 问卷中的题目 id 由问卷生成
    assert "logic" not in q
    assert locked(client, alice, v1["id"])                        # 加进问卷即锁定
    stored = db[SURVEYS].find_one({"_id": ObjectId(sid)})["questions"][0]["source"]
    assert stored["questionId"] == ObjectId(v1["id"])             # 数据库中存 ObjectId


def test_add_from_library_defaults_and_position(client, alice):
    sid = new_survey(client, alice)["id"]
    add_direct(client, alice, sid, type="text", title="第一题")
    add_direct(client, alice, sid, type="text", title="第二题")
    v1 = create(client, alice)
    s = ok(add_lib(client, alice, sid, v1["id"], position=2), 201)
    assert [q["title"] for q in s["questions"]] == ["第一题", "你的年龄", "第二题"]
    assert s["questions"][1]["validation"]["required"] is False
    r = add_lib(client, alice, sid, create(client, alice, GENDER)["id"], position=9)
    assert r.status_code == 422


def test_one_survey_can_use_a_question_once(client, alice):
    """同一道题（同一 rootId）在一份问卷中只能出现一次，换成别的版本也不行。"""
    v1 = create(client, alice)
    v2 = ok(derive(client, alice, v1["id"], title="v2"), 201)
    sid = new_survey(client, alice)["id"]
    ok(add_lib(client, alice, sid, v1["id"]), 201)
    for qid in (v1["id"], v2["id"]):
        r = add_lib(client, alice, sid, qid)
        assert r.status_code == 409 and r.json()["code"] == "QUESTION_ALREADY_IN_SURVEY"
    assert not locked(client, alice, v2["id"])   # 被拒绝时不加锁


def test_same_question_in_many_surveys(client, alice):
    """需求一：一个题目可以被多个问卷使用；需求五：A 问卷用旧题、B 问卷用新题。"""
    v1 = create(client, alice)
    v2 = ok(derive(client, alice, v1["id"], title="你的年龄（周岁）"), 201)
    a, b = new_survey(client, alice)["id"], new_survey(client, alice)["id"]
    sa = ok(add_lib(client, alice, a, v1["id"]), 201)
    sb = ok(add_lib(client, alice, b, v2["id"]), 201)
    assert sa["questions"][0]["title"] == "你的年龄" and sb["questions"][0]["title"] == "你的年龄（周岁）"


def test_permissions(client, alice, bob):
    v1 = create(client, alice)
    bob_survey = new_survey(client, bob)["id"]
    r = add_lib(client, bob, bob_survey, v1["id"])
    assert r.status_code == 404                                   # 没有共享：与不存在一样
    assert not locked(client, alice, v1["id"])
    ok(share(client, alice, v1["id"], ["bob"]))
    ok(add_lib(client, bob, bob_survey, v1["id"]), 201)           # 共享后可以用在自己的问卷中
    assert locked(client, alice, v1["id"])                        # 用在别人的问卷中也算用过
    # 不能往别人的问卷里加
    alice_survey = new_survey(client, alice)["id"]
    assert add_lib(client, bob, alice_survey, v1["id"]).status_code == 404


def test_only_draft(client, alice):
    v1 = create(client, alice)
    sid = new_survey(client, alice)["id"]
    add_direct(client, alice, sid, type="text", title="已有题")
    ok(client.post(f"/api/surveys/{sid}/publish", headers=alice))
    r = add_lib(client, alice, sid, v1["id"])
    assert r.status_code == 409 and r.json()["code"] == "INVALID_STATUS"
    assert not locked(client, alice, v1["id"])


def test_option_id_conflict_rejected(client, alice, db):
    v1 = create(client, alice, GENDER)
    sid = new_survey(client, alice)["id"]
    add_direct(client, alice, sid, type="single_choice", title="直接建的题", options=[{"text": "甲"}])
    # 构造冲突（实际中概率极低）：让问卷中已有题目的选项 id 与版本的选项 id 相同
    db[SURVEYS].update_one({"_id": ObjectId(sid)},
                           {"$set": {"questions.0.options.0.id": v1["options"][0]["id"]}})
    r = add_lib(client, alice, sid, v1["id"])
    assert r.status_code == 409 and r.json()["code"] == "OPTION_ID_CONFLICT"
    assert len(ok(client.get(f"/api/surveys/{sid}", headers=alice))["questions"]) == 1


def test_question_limit_checked_before_locking(client, alice, db):
    v1 = create(client, alice)
    sid = new_survey(client, alice)["id"]
    filler = [{"id": f"q_{i:06d}", "type": "text", "title": f"题 {i}", "validation": {"required": False}}
              for i in range(100)]
    db[SURVEYS].update_one({"_id": ObjectId(sid)}, {"$set": {"questions": filler}})
    assert add_lib(client, alice, sid, v1["id"]).status_code == 422
    assert not locked(client, alice, v1["id"])


# ---------- 修改问卷中来自题目库的题 ----------
def test_library_question_only_required_and_logic_editable(client, alice):
    v1 = create(client, alice, GENDER)
    sid = new_survey(client, alice)["id"]
    add_direct(client, alice, sid, type="text", title="结尾")
    s = ok(add_lib(client, alice, sid, v1["id"], position=1), 201)
    q, end = s["questions"]

    # 改是否必答、设跳转规则：可以，source 保留
    logic = {"rules": [{"when": {"op": "eq", "value": q["options"][0]["id"]}, "goto": "END"}],
             "defaultNext": None}
    s = ok(update(client, alice, sid, q, validation={"required": True}, logic=logic))
    q = s["questions"][0]
    assert q["validation"]["required"] is True and q["logic"] == logic
    assert q["source"]["questionId"] == v1["id"]

    # 改内容或校验：不可以
    for changes in ({"title": "改标题"},
                    {"options": [*q["options"], {"text": "新选项"}]},
                    {"options": [{"id": o["id"], "text": o["text"] + "!"} for o in q["options"]]},
                    {"options": q["options"][:1]}):
        r = update(client, alice, sid, q, **changes)
        assert r.status_code == 422 and r.json()["errors"][0]["field"] == "source", changes
    r = update(client, alice, sid, q, type="multiple_choice")
    assert r.status_code == 422
    # 问卷中直接建的题照常可以随意修改（第一阶段行为）
    s = ok(update(client, alice, sid, end, title="新的结尾"))
    assert s["questions"][1]["title"] == "新的结尾" and "source" not in s["questions"][1]


def test_library_number_validation_not_editable(client, alice):
    v1 = create(client, alice)
    sid = new_survey(client, alice)["id"]
    q = ok(add_lib(client, alice, sid, v1["id"]), 201)["questions"][0]
    r = update(client, alice, sid, q, validation={"required": False, "min": 18, "max": 150, "integerOnly": True})
    assert r.status_code == 422
    ok(update(client, alice, sid, q, validation={**q["validation"], "required": True}))


def test_source_field_cannot_be_written_by_client(client, alice):
    """source 由系统维护：添加、修改题目的请求中带 source 一律拒绝（第一阶段的请求模型不接受多余字段）。"""
    sid = new_survey(client, alice)["id"]
    fake = {"questionId": str(ObjectId()), "rootId": str(ObjectId()), "version": 1}
    r = client.post(f"/api/surveys/{sid}/questions", json={"type": "text", "title": "t", "source": fake},
                    headers=alice)
    assert r.status_code == 422
    q = add_direct(client, alice, sid, type="text", title="t")["questions"][0]
    assert update(client, alice, sid, q, source=fake).status_code == 422


# ---------- 修改题目不影响已有问卷（需求三） ----------
def test_changing_question_does_not_change_existing_survey(client, alice):
    v1 = create(client, alice)
    sid = new_survey(client, alice)["id"]
    ok(add_lib(client, alice, sid, v1["id"]), 201)
    ok(client.post(f"/api/surveys/{sid}/publish", headers=alice))
    # 用过的版本不能直接改，只能创建新版本
    r = client.put(f"/api/questions/{v1['id']}", json={**AGE, "title": "今年的问法"}, headers=alice)
    assert r.status_code == 409 and r.json()["code"] == "QUESTION_LOCKED"
    ok(derive(client, alice, v1["id"], title="今年的问法"), 201)
    # 去年的问卷不变
    assert ok(client.get(f"/api/surveys/{sid}", headers=alice))["questions"][0]["title"] == "你的年龄"


def test_lock_is_permanent(client, alice):
    """题目从问卷中删除、草稿问卷被删除，版本都不解锁（10.4 第 2 条）。"""
    v1 = create(client, alice)
    sid = new_survey(client, alice)["id"]
    q = ok(add_lib(client, alice, sid, v1["id"]), 201)["questions"][0]
    ok(client.delete(f"/api/surveys/{sid}/questions/{q['id']}", headers=alice))
    assert locked(client, alice, v1["id"])
    assert client.delete(f"/api/surveys/{sid}", headers=alice).status_code == 204
    assert locked(client, alice, v1["id"])
    assert client.delete(f"/api/questions/{v1['id']}", headers=alice).status_code == 409


def test_lock_before_copy_blocks_concurrent_edit(client, alice, monkeypatch):
    """加锁后才读取内容复制：加锁之后到来的直接修改会失败，问卷中的副本与版本内容一致。"""
    from app.services import question_library as library
    v1 = create(client, alice)
    sid = new_survey(client, alice)["id"]
    real_lock = library.lock_for_use
    attempts = []

    def lock_then_edit(db_, user_id, question_id):
        doc = real_lock(db_, user_id, question_id)
        attempts.append(client.put(f"/api/questions/{v1['id']}", json={**AGE, "title": "并发修改"},
                                   headers=alice).status_code)
        return doc

    monkeypatch.setattr(library, "lock_for_use", lock_then_edit)
    s = ok(add_lib(client, alice, sid, v1["id"]), 201)
    assert attempts == [409]
    assert s["questions"][0]["title"] == ok(client.get(f"/api/questions/{v1['id']}", headers=alice))["title"]


# ---------- 换版本（需求七：题库里的题可以更新版本） ----------
def test_switch_version_keeps_id_required_and_logic(client, alice):
    v1 = create(client, alice, GENDER)
    sid = new_survey(client, alice)["id"]
    add_direct(client, alice, sid, type="text", title="结尾")
    q = ok(add_lib(client, alice, sid, v1["id"], position=1, required=True), 201)["questions"][0]
    female = q["options"][1]["id"]
    logic = {"rules": [{"when": {"op": "eq", "value": female}, "goto": "END"}], "defaultNext": None}
    ok(update(client, alice, sid, q, logic=logic))
    v2 = ok(derive(client, alice, v1["id"], title="你的性别",
                   options=[*v1["options"], {"text": "不愿透露"}]), 201)

    s = ok(switch(client, alice, sid, q["id"], v2["id"]))
    nq = s["questions"][0]
    assert nq["id"] == q["id"] and nq["title"] == "你的性别" and len(nq["options"]) == 3
    assert nq["validation"]["required"] is True and nq["logic"] == logic
    assert nq["source"] == {"questionId": v2["id"], "rootId": v1["rootId"], "version": 2}
    assert locked(client, alice, v2["id"])


def test_switch_rejected_when_rule_option_missing(client, alice):
    v1 = create(client, alice, GENDER)
    sid = new_survey(client, alice)["id"]
    add_direct(client, alice, sid, type="text", title="结尾")
    q = ok(add_lib(client, alice, sid, v1["id"], position=1), 201)["questions"][0]
    male = q["options"][0]["id"]
    ok(update(client, alice, sid, q, logic={"rules": [{"when": {"op": "eq", "value": male}, "goto": "END"}],
                                             "defaultNext": None}))
    v2 = ok(derive(client, alice, v1["id"], options=[v1["options"][1]]), 201)   # 删掉了“男”
    r = switch(client, alice, sid, q["id"], v2["id"])
    assert r.status_code == 422 and male in r.json()["errors"][0]["message"]
    assert ok(client.get(f"/api/surveys/{sid}", headers=alice))["questions"][0]["source"]["version"] == 1


def test_switch_version_errors(client, alice):
    v1 = create(client, alice)
    other = create(client, alice, GENDER)
    sid = new_survey(client, alice)["id"]
    s = ok(add_lib(client, alice, sid, v1["id"]), 201)
    direct = add_direct(client, alice, sid, type="text", title="直接建的题")["questions"][1]
    lib_q = s["questions"][0]

    r = switch(client, alice, sid, lib_q["id"], other["id"])           # 另一道题
    assert r.status_code == 422
    r = switch(client, alice, sid, direct["id"], v1["id"])             # 问卷中直接建的题没有来源
    assert r.status_code == 409 and r.json()["code"] == "NOT_FROM_LIBRARY"
    assert switch(client, alice, sid, "q_nothere", v1["id"]).status_code == 404
    assert ok(switch(client, alice, sid, lib_q["id"], v1["id"]))["questions"][0]["source"]["version"] == 1

    v2 = ok(derive(client, alice, v1["id"], title="v2"), 201)
    ok(client.post(f"/api/surveys/{sid}/publish", headers=alice))
    r = switch(client, alice, sid, lib_q["id"], v2["id"])              # 发布后不能换
    assert r.status_code == 409 and r.json()["code"] == "INVALID_STATUS"
    assert not locked(client, alice, v2["id"])


# ---------- 填写、跳转、校验、统计 ----------
def test_fill_and_stats_with_library_questions(client, alice, bob):
    gender = create(client, alice, GENDER)
    age = create(client, alice)
    sid = new_survey(client, alice)["id"]
    s = ok(add_lib(client, alice, sid, gender["id"], required=True), 201)
    s = ok(add_lib(client, alice, sid, age["id"], required=True), 201)
    s = add_direct(client, alice, sid, type="text", title="建议")
    g, a, t = s["questions"]
    # 选“女”直接结束：跳转规则在问卷中设置
    ok(update(client, alice, sid, g, logic={"rules": [{"when": {"op": "eq", "value": g["options"][1]["id"]},
                                                        "goto": "END"}], "defaultNext": None}))
    code = ok(client.post(f"/api/surveys/{sid}/publish", headers=alice))["shortCode"]

    view = ok(get(client, bob, code))
    assert all("source" not in q for q in view["questions"])      # 填写者看不到来源信息

    r = submit(client, bob, code, {g["id"]: g["options"][0]["id"], a["id"]: 200})   # 超出 0~150
    assert r.status_code == 422
    ok(submit(client, bob, code, {g["id"]: g["options"][0]["id"], a["id"]: 20, t["id"]: "无"}), 201)

    stats = ok(client.get(f"/api/surveys/{sid}/stats", headers=alice))
    by_id = {q["questionId"]: q for q in stats["questions"]}
    assert [o["count"] for o in by_id[g["id"]]["options"]] == [1, 0]
    assert by_id[a["id"]]["average"] == 20


def test_respondent_view_whitelist_unchanged(client, alice, bob):
    """填写者看到的题目字段与第一阶段相同：id、type、title、options、validation。"""
    v1 = create(client, alice, GENDER)
    sid = new_survey(client, alice)["id"]
    ok(add_lib(client, alice, sid, v1["id"]), 201)
    code = ok(client.post(f"/api/surveys/{sid}/publish", headers=alice))["shortCode"]
    q = ok(get(client, bob, code))["questions"][0]
    assert set(q) == {"id", "type", "title", "options", "validation"}


def test_phase1_style_survey_unaffected(client, alice, db):
    """直接写入第一阶段格式的问卷（没有 source），第二阶段代码下照常读取、编辑、发布。"""
    sid = new_survey(client, alice)["id"]
    add_direct(client, alice, sid, type="number", title="旧题", validation={"min": 0})
    s = ok(client.get(f"/api/surveys/{sid}", headers=alice))
    assert all("source" not in q for q in s["questions"])
    q = s["questions"][0]
    s = ok(update(client, alice, sid, q, title="旧题改名", validation={"required": True, "min": 1}))
    assert s["questions"][0]["title"] == "旧题改名" and "source" not in s["questions"][0]
    ok(client.post(f"/api/surveys/{sid}/publish", headers=alice))
    assert db[QUESTIONS].count_documents({}) == 0   # 没有产生任何题目库记录
