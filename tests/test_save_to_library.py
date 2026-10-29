"""第二阶段第 6 步：把问卷里的题存进题目库（设计文档 10.5）。

- 生成新题 v1：选项 id 沿用，validation 去掉 required，不含跳转规则；v1 已被这份问卷使用，创建即锁定
- 给原问卷的题补上 source，不改题目内容；已发布、已关闭的问卷也可以，答卷和统计不变
- 已有 source 的题不能再存；失败时撤销刚创建的 v1
"""
from bson import ObjectId

from app.db import QUESTIONS, SURVEYS
from tests.builders import build_fruit_survey
from tests.test_fill import submit
from tests.test_question_library import ok
from tests.test_survey_library import add_lib, locked, new_survey, update


def save(client, headers, sid, qid):
    return client.post(f"/api/surveys/{sid}/questions/{qid}/save-to-library", headers=headers)


def without_source(q: dict) -> dict:
    return {k: v for k, v in q.items() if k != "source"}


# ---------- 基本行为 ----------
def test_save_draft_question(client, alice, db):
    built = build_fruit_survey(client, alice, publish=False)
    sid, q2 = built["survey"]["id"], built["q"][1]      # 多选，必答，minSelect 1、maxSelect 3，有跳转规则
    result = ok(save(client, alice, sid, q2["id"]), 201)

    v1 = result["question"]
    assert v1["version"] == 1 and v1["rootId"] == v1["id"] and v1["parentId"] is None
    assert v1["owner"] == "alice" and v1["locked"] is True
    assert v1["sharing"] == {"public": False, "userIds": [], "usernames": []}
    assert v1["type"] == q2["type"] and v1["title"] == q2["title"]
    assert v1["options"] == q2["options"]                               # 选项 id 沿用
    assert v1["validation"] == {"minSelect": 1, "maxSelect": 3}         # 去掉 required
    stored = db[QUESTIONS].find_one({"_id": ObjectId(v1["id"])})
    assert "logic" not in stored and "required" not in stored["validation"]

    after = result["survey"]["questions"][1]
    assert without_source(after) == q2                                  # 题目内容、必答、跳转规则都不变
    assert after["source"] == {"questionId": v1["id"], "rootId": v1["id"], "version": 1}
    assert result["survey"]["updatedAt"] > built["survey"]["updatedAt"]
    # 其他题不受影响
    assert result["survey"]["questions"][0] == built["q"][0]


def test_save_text_question(client, alice):
    built = build_fruit_survey(client, alice, publish=False)
    q3 = built["q"][2]
    v1 = ok(save(client, alice, built["survey"]["id"], q3["id"]), 201)["question"]
    assert v1["options"] is None and v1["validation"] == {"minLength": 5, "maxLength": 200}


def test_saved_question_is_restricted_in_draft(client, alice):
    """存入后，这道题在问卷中就是来自题目库的题：只能改是否必答和跳转规则。"""
    built = build_fruit_survey(client, alice, publish=False)
    sid, q4 = built["survey"]["id"], built["q"][3]
    q4 = ok(save(client, alice, sid, q4["id"]), 201)["survey"]["questions"][3]
    assert update(client, alice, sid, q4, title="改标题").status_code == 422
    ok(update(client, alice, sid, q4, validation={**q4["validation"], "required": False}))


# ---------- 已发布、已关闭的问卷 ----------
def test_save_from_published_survey_keeps_responses(client, alice, bob, db):
    built = build_fruit_survey(client, alice, submissionPolicy="all")   # 存入后再填一次
    sid, code = built["survey"]["id"], built["survey"]["shortCode"]
    q1, q4 = built["q"][0], built["q"][3]
    ok(submit(client, bob, code, {q1["id"]: built["o"]["不喜欢"], built["q"][4]["id"]: "无"}), 201)
    before = ok(client.get(f"/api/surveys/{sid}/stats", headers=alice))

    result = ok(save(client, alice, sid, q1["id"]), 201)
    assert result["survey"]["status"] == "published"
    assert without_source(result["survey"]["questions"][0]) == q1
    after = ok(client.get(f"/api/surveys/{sid}/stats", headers=alice))
    assert after["questions"] == before["questions"]                    # 统计不变
    # 存入后仍可以继续填写
    ok(submit(client, bob, code, {q1["id"]: built["o"]["不喜欢"], built["q"][4]["id"]: "再填一次"}), 201)
    ok(save(client, alice, sid, q4["id"]), 201)


def test_save_from_closed_survey(client, alice):
    built = build_fruit_survey(client, alice)
    sid = built["survey"]["id"]
    ok(client.post(f"/api/surveys/{sid}/close", headers=alice))
    result = ok(save(client, alice, sid, built["q"][0]["id"]), 201)
    assert result["survey"]["status"] == "closed"


def test_save_phase1_survey_written_directly(client, alice, db):
    """第一阶段留下的问卷（直接以旧格式写入数据库，没有 source）也可以存入。"""
    sid = new_survey(client, alice)["id"]
    old_q = {"id": "q_old001", "type": "number", "title": "旧问卷的题",
             "validation": {"required": True, "min": 0, "max": 10, "integerOnly": True}}
    db[SURVEYS].update_one({"_id": ObjectId(sid)}, {"$set": {"questions": [old_q], "status": "closed"}})
    result = ok(save(client, alice, sid, "q_old001"), 201)
    assert without_source(result["survey"]["questions"][0]) == old_q
    assert result["question"]["validation"] == {"min": 0, "max": 10, "integerOnly": True}


# ---------- 存入后的版本 ----------
def test_saved_version_can_be_reused_and_derived(client, alice):
    built = build_fruit_survey(client, alice, publish=False)
    sid, q1 = built["survey"]["id"], built["q"][0]
    v1 = ok(save(client, alice, sid, q1["id"]), 201)["question"]
    # 已被原问卷使用：不能直接改，可以创建新版本
    body = {"type": v1["type"], "title": "改", "options": v1["options"]}
    assert client.put(f"/api/questions/{v1['id']}", json=body, headers=alice).status_code == 409
    assert ok(client.post(f"/api/questions/{v1['id']}/versions", json=body, headers=alice), 201)["version"] == 2
    # 同一份问卷中不能再加一次（同一道题）；别的问卷可以用
    assert add_lib(client, alice, sid, v1["id"]).status_code == 409
    other = new_survey(client, alice)["id"]
    s = ok(add_lib(client, alice, other, v1["id"]), 201)
    assert s["questions"][0]["options"] == q1["options"]


# ---------- 拒绝的情况 ----------
def test_cannot_save_twice_or_library_question(client, alice, db):
    built = build_fruit_survey(client, alice, publish=False)
    sid, q1 = built["survey"]["id"], built["q"][0]
    v1 = ok(save(client, alice, sid, q1["id"]), 201)["question"]
    r = save(client, alice, sid, q1["id"])
    assert r.status_code == 409 and r.json()["code"] == "ALREADY_IN_LIBRARY"
    # 从题目库加进来的题同样不能再存
    other = new_survey(client, alice)["id"]
    lib_q = ok(add_lib(client, alice, other, v1["id"]), 201)["questions"][0]
    assert save(client, alice, other, lib_q["id"]).status_code == 409
    assert db[QUESTIONS].count_documents({}) == 1


def test_permissions_and_not_found(client, alice, bob, db):
    built = build_fruit_survey(client, alice, publish=False)
    sid, q1 = built["survey"]["id"], built["q"][0]
    assert save(client, bob, sid, q1["id"]).status_code == 404          # 别人的问卷
    assert save(client, alice, sid, "q_nothere").status_code == 404
    assert save(client, alice, str(ObjectId()), q1["id"]).status_code == 404
    assert client.post(f"/api/surveys/{sid}/questions/{q1['id']}/save-to-library").status_code == 401
    assert db[QUESTIONS].count_documents({}) == 0


# ---------- 并发 ----------
def test_concurrent_edit_undoes_new_version(client, alice, db, monkeypatch):
    """创建 v1 后、补 source 前问卷被修改：返回 409，撤销 v1，问卷保持另一个请求修改后的样子。"""
    from app.services import question_library as library
    built = build_fruit_survey(client, alice, publish=False)
    sid, q1, q5 = built["survey"]["id"], built["q"][0], built["q"][4]
    real = library.create_from_survey_question

    def create_then_other_edit(db_, owner_id, question):
        doc = real(db_, owner_id, question)
        assert update(client, alice, sid, q5, title="另一个请求改的").status_code == 200
        return doc

    monkeypatch.setattr(library, "create_from_survey_question", create_then_other_edit)
    r = save(client, alice, sid, q1["id"])
    assert r.status_code == 409 and r.json()["code"] == "EDIT_CONFLICT"
    assert db[QUESTIONS].count_documents({}) == 0
    s = ok(client.get(f"/api/surveys/{sid}", headers=alice))
    assert s["questions"][4]["title"] == "另一个请求改的" and "source" not in s["questions"][0]


def test_concurrent_double_save_leaves_one_version(client, alice, db, monkeypatch):
    """同一道题同时存两次：只有一次成功，另一次撤销自己的 v1，最后只有一道题。"""
    from app.services import question_library as library
    from app.services import questions as service
    built = build_fruit_survey(client, alice, publish=False)
    sid, q1 = built["survey"]["id"], built["q"][0]
    real = library.create_from_survey_question
    inner = {}

    def create_then_other_save(db_, owner_id, question):
        doc = real(db_, owner_id, question)
        if not inner:
            monkeypatch.setattr(library, "create_from_survey_question", real)
            inner["result"] = service.save_to_library(db_, owner_id, sid, q1["id"])
        return doc

    monkeypatch.setattr(library, "create_from_survey_question", create_then_other_save)
    r = save(client, alice, sid, q1["id"])
    assert r.status_code == 409 and r.json()["code"] == "ALREADY_IN_LIBRARY"
    winner = inner["result"][1]
    assert [d["_id"] for d in db[QUESTIONS].find()] == [winner["_id"]]
    s = ok(client.get(f"/api/surveys/{sid}", headers=alice))
    assert s["questions"][0]["source"]["questionId"] == str(winner["_id"])
    assert locked(client, alice, str(winner["_id"]))
