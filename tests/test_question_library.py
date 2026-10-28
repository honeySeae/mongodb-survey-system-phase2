"""第二阶段第 3 步：题目与版本接口（设计文档 10.2、10.4、10.6、10.9）。

共享设置的接口在第 4 步实现；这里需要“共享给 bob”的场景时直接改数据库。
锁定（加进问卷）在第 5 步实现；这里需要“已锁定”的场景时直接改数据库。
"""
from bson import ObjectId

from app.db import QUESTION_BANKS, QUESTIONS
from app.utils import now_utc

AGE = {"type": "number", "title": "你的年龄", "validation": {"min": 0, "max": 150, "integerOnly": True}}
GENDER = {"type": "single_choice", "title": "性别", "options": [{"text": "男"}, {"text": "女"}]}


def ok(resp, status=200):
    assert resp.status_code == status, resp.json()
    return resp.json()


def create(client, headers, body=AGE):
    return ok(client.post("/api/questions", json=body, headers=headers), 201)


def derive(client, headers, qid, **changes):
    base = ok(client.get(f"/api/questions/{qid}", headers=headers))
    body = {"type": base["type"], "title": base["title"], "validation": base["validation"]}
    if base.get("options") is not None:
        body["options"] = [{"id": o["id"], "text": o["text"]} for o in base["options"]]
    body.update(changes)
    return client.post(f"/api/questions/{qid}/versions", json=body, headers=headers)


def share_with(db, qid, user_id=None, public=False):
    db[QUESTIONS].update_many({"_id": ObjectId(qid)}, {"$set": {
        "sharing": {"public": public, "userIds": [user_id] if user_id else []}}})


def lock(db, qid):
    db[QUESTIONS].update_one({"_id": ObjectId(qid)}, {"$set": {"lockedAt": now_utc()}})


def user_id(db, username):
    return db["users"].find_one({"username": username})["_id"]


# ---------- 新建 ----------
def test_create_question_v1(client, alice, db):
    q = create(client, alice)
    assert q["version"] == 1 and q["rootId"] == q["id"] and q["parentId"] is None
    assert q["restoredFrom"] is None and q["owner"] == "alice" and q["isMine"] is True
    assert q["locked"] is False and q["sharing"] == {"public": False, "userIds": []}
    stored = db[QUESTIONS].find_one({"_id": ObjectId(q["id"])})
    assert stored["rootId"] == stored["_id"] and "required" not in stored["validation"]


def test_create_rejects_required_and_bad_content(client, alice):
    r = client.post("/api/questions", json={**AGE, "validation": {"required": True}}, headers=alice)
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "validation.required"
    r = client.post("/api/questions", json={"type": "single_choice", "title": "空选项", "options": []},
                    headers=alice)
    assert r.status_code == 422
    r = client.post("/api/questions", json={**AGE, "logic": {}}, headers=alice)  # 题目中不存跳转规则
    assert r.status_code == 422


def test_requires_login(client):
    assert client.get("/api/questions").status_code == 401
    assert client.post("/api/questions", json=AGE).status_code == 401


# ---------- 派生新版本、历史 ----------
def test_v1_v2_v3_chain_and_history(client, alice):
    """需求四的示例：v1 → v2 → v3，能看到版本关系。"""
    v1 = create(client, alice)
    v2 = ok(derive(client, alice, v1["id"], title="你的年龄（周岁）"), 201)
    v3 = ok(derive(client, alice, v2["id"], validation={"min": 0, "max": 120, "integerOnly": True}), 201)
    assert (v2["version"], v2["parentId"], v2["rootId"]) == (2, v1["id"], v1["id"])
    assert (v3["version"], v3["parentId"]) == (3, v2["id"])

    h = ok(client.get(f"/api/questions/{v3['id']}/history", headers=alice))
    assert h["rootId"] == v1["id"]
    assert [(n["version"], n["parentId"]) for n in h["versions"]] == [
        (1, None), (2, v1["id"]), (3, v2["id"])]
    assert all(n["accessible"] for n in h["versions"])
    # 旧版本内容不变（需求三、五：不同版本同时存在）
    assert ok(client.get(f"/api/questions/{v1['id']}", headers=alice))["title"] == "你的年龄"


def test_branching_versions(client, alice):
    """从 v1 同时派生两个版本：历史是一棵树，版本号按创建先后编号。"""
    v1 = create(client, alice)
    a = ok(derive(client, alice, v1["id"], title="A"), 201)
    b = ok(derive(client, alice, v1["id"], title="B"), 201)
    assert (a["version"], b["version"]) == (2, 3)
    assert a["parentId"] == b["parentId"] == v1["id"]


def test_derive_cannot_change_type(client, alice):
    v1 = create(client, alice)
    r = derive(client, alice, v1["id"], type="text", validation={})
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "type"


def test_derive_keeps_option_ids(client, alice):
    v1 = create(client, alice, GENDER)
    male, female = v1["options"]
    v2 = ok(derive(client, alice, v1["id"], options=[
        {"id": female["id"], "text": "女性"}, {"text": "不愿透露"}]), 201)
    assert v2["options"][0] == {"id": female["id"], "text": "女性"}
    new_id = v2["options"][1]["id"]
    assert new_id not in (male["id"], female["id"])
    # v2 中删掉了“男”；基于 v2 再派生时不能拿回 v1 的“男”的 id
    r = derive(client, alice, v2["id"], options=[{"id": male["id"], "text": "男"}])
    assert r.status_code == 422
    # 新增的选项 id 不会与这道题任何版本用过的 id 重复
    v3 = ok(derive(client, alice, v2["id"], options=[{"text": "男"}]), 201)
    assert v3["options"][0]["id"] not in (male["id"], female["id"], new_id)


def test_derive_from_locked_version_allowed(client, alice, db):
    v1 = create(client, alice)
    lock(db, v1["id"])
    assert ok(derive(client, alice, v1["id"], title="新的"), 201)["version"] == 2


# ---------- 直接修改 ----------
def test_update_unlocked_version(client, alice):
    v1 = create(client, alice, GENDER)
    body = {"type": "single_choice", "title": "你的性别",
            "options": [{"id": v1["options"][0]["id"], "text": "男"}, {"text": "其他"}]}
    q = ok(client.put(f"/api/questions/{v1['id']}", json=body, headers=alice))
    assert q["title"] == "你的性别" and q["version"] == 1
    assert q["options"][0]["id"] == v1["options"][0]["id"]
    assert q["updatedAt"] > v1["updatedAt"]


def test_update_locked_version_rejected(client, alice, db):
    v1 = create(client, alice)
    lock(db, v1["id"])
    r = client.put(f"/api/questions/{v1['id']}", json={**AGE, "title": "改"}, headers=alice)
    assert r.status_code == 409 and r.json()["code"] == "QUESTION_LOCKED"
    assert ok(client.get(f"/api/questions/{v1['id']}", headers=alice))["locked"] is True


def test_update_cannot_change_type(client, alice):
    v1 = create(client, alice)
    r = client.put(f"/api/questions/{v1['id']}", json={"type": "text", "title": "x"}, headers=alice)
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "type"


def test_update_expected_updated_at(client, alice):
    v1 = create(client, alice)
    ok(client.put(f"/api/questions/{v1['id']}", json={**AGE, "title": "第一次"}, headers=alice))
    r = client.put(f"/api/questions/{v1['id']}", json={**AGE, "title": "第二次"}, headers=alice,
                   params={"expectedUpdatedAt": v1["updatedAt"]})
    assert r.status_code == 409 and r.json()["code"] == "EDIT_CONFLICT"


# ---------- 恢复 ----------
def test_restore_old_version(client, alice):
    v1 = create(client, alice)
    v2 = ok(derive(client, alice, v1["id"], title="改坏了"), 201)
    v3 = ok(client.post(f"/api/questions/{v1['id']}/restore", headers=alice), 201)
    assert v3["version"] == 3 and v3["restoredFrom"] == v1["id"]
    assert v3["parentId"] == v2["id"]   # 默认接在自己版本号最大的版本后面
    assert v3["title"] == v1["title"] and v3["validation"] == v1["validation"]
    assert ok(client.get(f"/api/questions/{v2['id']}", headers=alice))["title"] == "改坏了"  # 旧版本不变


def test_restore_with_explicit_parent(client, alice):
    v1 = create(client, alice)
    v2 = ok(derive(client, alice, v1["id"], title="B"), 201)
    ok(derive(client, alice, v1["id"], title="C"), 201)
    v4 = ok(client.post(f"/api/questions/{v1['id']}/restore", json={"parentId": v2["id"]},
                        headers=alice), 201)
    assert v4["parentId"] == v2["id"] and v4["restoredFrom"] == v1["id"]


def test_restore_parent_must_be_same_question(client, alice):
    v1 = create(client, alice)
    other = create(client, alice, GENDER)
    r = client.post(f"/api/questions/{v1['id']}/restore", json={"parentId": other["id"]}, headers=alice)
    assert r.status_code == 422


def test_restore_keeps_option_ids(client, alice):
    v1 = create(client, alice, GENDER)
    ok(derive(client, alice, v1["id"], options=[{"text": "甲"}]), 201)
    v3 = ok(client.post(f"/api/questions/{v1['id']}/restore", headers=alice), 201)
    assert v3["options"] == v1["options"]


# ---------- 共享后的权限（共享接口在第 4 步） ----------
def test_others_cannot_see_private_question(client, alice, bob):
    v1 = create(client, alice)
    assert client.get(f"/api/questions/{v1['id']}", headers=bob).status_code == 404
    r = client.post(f"/api/questions/{v1['id']}/versions", json=AGE, headers=bob)
    assert r.status_code == 404
    assert client.get(f"/api/questions/{v1['id']}/history", headers=bob).status_code == 404
    assert client.delete(f"/api/questions/{v1['id']}", headers=bob).status_code == 404
    assert client.get("/api/questions/not-an-id", headers=bob).status_code == 404


def test_shared_user_can_use_and_derive_but_not_modify(client, alice, bob, db):
    v1 = create(client, alice)
    share_with(db, v1["id"], user_id(db, "bob"))
    seen = ok(client.get(f"/api/questions/{v1['id']}", headers=bob))
    assert seen["isMine"] is False and seen["owner"] == "alice" and seen["sharing"] is None  # 不暴露共享名单
    r = client.put(f"/api/questions/{v1['id']}", json={**AGE, "title": "bob 改"}, headers=bob)
    assert r.status_code == 403 and r.json()["code"] == "NOT_OWNER"
    assert client.delete(f"/api/questions/{v1['id']}", headers=bob).status_code == 403
    # bob 基于它创建自己的版本：属于 bob，默认不共享
    mine = ok(derive(client, bob, v1["id"], title="bob 的版本"), 201)
    assert mine["owner"] == "bob" and mine["version"] == 2 and mine["parentId"] == v1["id"]
    assert mine["sharing"] == {"public": False, "userIds": []}


def test_new_version_inherits_own_sharing(client, alice, bob, db):
    v1 = create(client, alice)
    share_with(db, v1["id"], public=True)
    v2 = ok(derive(client, alice, v1["id"], title="v2"), 201)
    assert v2["sharing"]["public"] is True
    v3 = ok(client.post(f"/api/questions/{v1['id']}/restore", headers=alice), 201)
    assert v3["sharing"]["public"] is True


def test_history_hides_inaccessible_versions(client, alice, bob, db):
    """bob 派生的版本没有共享：alice 看历史时只看到占位节点；bob 能看到 alice 共享的版本。"""
    v1 = create(client, alice)
    share_with(db, v1["id"], user_id(db, "bob"))
    b2 = ok(derive(client, bob, v1["id"], title="bob 私有"), 201)

    h = ok(client.get(f"/api/questions/{v1['id']}/history", headers=alice))
    node = h["versions"][1]
    assert node == {"id": b2["id"], "version": 2, "parentId": v1["id"], "restoredFrom": None,
                    "accessible": False, "detail": None}
    hb = ok(client.get(f"/api/questions/{b2['id']}/history", headers=bob))
    assert [n["accessible"] for n in hb["versions"]] == [True, True]


def test_restore_others_version_defaults_parent_to_source(client, alice, bob, db):
    """bob 在这道题下还没有自己的版本：恢复时默认接在被恢复的版本后面，新版本属于 bob。"""
    v1 = create(client, alice)
    v2 = ok(derive(client, alice, v1["id"], title="v2"), 201)
    db[QUESTIONS].update_many({"rootId": ObjectId(v1["id"])},
                              {"$set": {"sharing": {"public": True, "userIds": []}}})
    r = ok(client.post(f"/api/questions/{v1['id']}/restore", headers=bob), 201)
    assert r["owner"] == "bob" and r["parentId"] == v1["id"] and r["restoredFrom"] == v1["id"]
    assert r["sharing"] == {"public": False, "userIds": []}
    assert r["version"] == 3 and v2["version"] == 2


# ---------- 列表 ----------
def test_list_scopes(client, alice, bob, db):
    a1 = create(client, alice)
    a2 = create(client, alice, GENDER)
    share_with(db, a1["id"], user_id(db, "bob"))
    share_with(db, a2["id"], public=True)
    b1 = create(client, bob)

    def ids(headers, scope, **params):
        data = ok(client.get("/api/questions", params={"scope": scope, **params}, headers=headers))
        return {i["id"] for i in data["items"]}, data["total"]

    assert ids(bob, "mine") == ({b1["id"]}, 1)
    assert ids(bob, "shared") == ({a1["id"]}, 1)
    assert ids(bob, "public") == ({a2["id"]}, 1)
    assert ids(bob, "all") == ({a1["id"], a2["id"], b1["id"]}, 3)
    assert ids(alice, "public") == (set(), 0)   # 公开列表不含自己的
    assert ids(alice, "mine", rootId=a1["id"]) == ({a1["id"]}, 1)
    assert client.get("/api/questions", params={"scope": "everyone"}, headers=bob).status_code == 422


def test_list_pagination(client, alice):
    for i in range(5):
        create(client, alice, {**AGE, "title": f"题 {i}"})
    page = ok(client.get("/api/questions", params={"limit": 2, "offset": 1}, headers=alice))
    assert page["total"] == 5 and len(page["items"]) == 2
    assert [i["title"] for i in page["items"]] == ["题 3", "题 2"]  # 最近修改的在前


# ---------- 删除 ----------
def test_delete_unused_leaf_version(client, alice):
    v1 = create(client, alice)
    assert client.delete(f"/api/questions/{v1['id']}", headers=alice).status_code == 204
    assert client.get(f"/api/questions/{v1['id']}", headers=alice).status_code == 404


def test_delete_rules(client, alice, db):
    v1 = create(client, alice)
    v2 = ok(derive(client, alice, v1["id"], title="v2"), 201)
    r = client.delete(f"/api/questions/{v1['id']}", headers=alice)
    assert r.status_code == 409 and r.json()["code"] == "QUESTION_HAS_CHILDREN"

    lock(db, v2["id"])
    r = client.delete(f"/api/questions/{v2['id']}", headers=alice)
    assert r.status_code == 409 and r.json()["code"] == "QUESTION_LOCKED"

    v3 = ok(client.post(f"/api/questions/{v1['id']}/restore", headers=alice), 201)
    db[QUESTION_BANKS].insert_one({
        "ownerId": ObjectId(), "name": "别人的题库", "description": "",
        "items": [{"questionId": ObjectId(v3["id"]), "rootId": ObjectId(v1["id"]), "addedAt": now_utc()}],
        "sharing": {"public": False, "userIds": []}, "createdAt": now_utc(), "updatedAt": now_utc()})
    r = client.delete(f"/api/questions/{v3['id']}", headers=alice)
    assert r.status_code == 409 and r.json()["code"] == "QUESTION_IN_BANK"


def test_restored_from_counts_as_child(client, alice):
    """只是恢复来源（不是任何版本的父版本）的版本也不能删。"""
    v1 = create(client, alice)
    v2 = ok(derive(client, alice, v1["id"], title="v2"), 201)
    v3 = ok(client.post(f"/api/questions/{v2['id']}/restore", json={"parentId": v1["id"]},
                        headers=alice), 201)
    assert v3["parentId"] == v1["id"] and v3["restoredFrom"] == v2["id"]
    r = client.delete(f"/api/questions/{v2['id']}", headers=alice)  # v2 没有子版本，但 v3 恢复自它
    assert r.status_code == 409 and r.json()["code"] == "QUESTION_HAS_CHILDREN"
    assert client.delete(f"/api/questions/{v3['id']}", headers=alice).status_code == 204


def test_version_number_retry_on_conflict(client, alice, db, monkeypatch):
    """模拟并发：第一次取到的版本号已被占用，重新取号后成功。"""
    from app.repositories import questions as repo
    v1 = create(client, alice)
    real = repo.max_version
    calls = {"n": 0}

    def stale(db_, root_id):
        calls["n"] += 1
        return 0 if calls["n"] == 1 else real(db_, root_id)  # 第一次返回过期的值 → 版本号 1 冲突

    monkeypatch.setattr(repo, "max_version", stale)
    v2 = ok(derive(client, alice, v1["id"], title="v2"), 201)
    assert v2["version"] == 2 and calls["n"] == 2


def test_derive_undone_if_parent_deleted_concurrently(client, alice, db, monkeypatch):
    """派生插入后发现父版本已被删除：撤销刚插入的版本并返回 404，不留下孤立版本。"""
    from app.repositories import questions as repo
    v1 = create(client, alice)
    real_insert = repo.insert

    def insert_then_parent_deleted(db_, doc):
        result = real_insert(db_, doc)
        db_[QUESTIONS].delete_one({"_id": ObjectId(v1["id"])})
        return result

    monkeypatch.setattr(repo, "insert", insert_then_parent_deleted)
    assert derive(client, alice, v1["id"], title="v2").status_code == 404
    assert db[QUESTIONS].count_documents({}) == 0
