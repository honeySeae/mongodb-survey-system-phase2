"""第二阶段第 4 步：题目共享（设计文档 10.6、10.9）。

- 以整道题为单位：设置时作用于所有者在这道题下的所有版本
- 新版本继承自己在这道题上的共享设置；别人派生的版本属于别人、默认不共享
- 被共享的人只能查看、使用、派生，不能修改、不能改共享设置；共享名单只返回给所有者
"""
from bson import ObjectId

from app.db import QUESTIONS
from tests.conftest import auth_headers_for
from tests.test_question_library import AGE, GENDER, create, derive, ok


def share(client, headers, qid, usernames=(), public=False):
    return client.put(f"/api/questions/{qid}/sharing",
                      json={"public": public, "usernames": list(usernames)}, headers=headers)


def visible(client, headers, qid) -> bool:
    return client.get(f"/api/questions/{qid}", headers=headers).status_code == 200


# ---------- 共享给指定用户 ----------
def test_share_with_user(client, alice, bob):
    carol = auth_headers_for(client, "carol")
    v1 = create(client, alice)
    result = ok(share(client, alice, v1["id"], ["bob"]))
    assert result["updatedVersions"] == 1
    assert result["question"]["sharing"]["usernames"] == ["bob"]

    assert visible(client, bob, v1["id"]) and not visible(client, carol, v1["id"])
    shared = ok(client.get("/api/questions", params={"scope": "shared"}, headers=bob))
    assert [i["id"] for i in shared["items"]] == [v1["id"]]
    # 被共享的人可以基于它创建自己的版本（需求二：其他用户可以使用这些题目）
    assert ok(derive(client, bob, v1["id"], title="bob 的版本"), 201)["owner"] == "bob"


def test_share_covers_all_own_versions_in_question(client, alice, bob):
    """以整道题为单位：通过任意一个版本设置，自己在这道题下的所有版本一起共享。"""
    v1 = create(client, alice)
    v2 = ok(derive(client, alice, v1["id"], title="v2"), 201)
    v3 = ok(derive(client, alice, v2["id"], title="v3"), 201)
    other = create(client, alice, GENDER)   # 另一道题不受影响
    assert ok(share(client, alice, v2["id"], ["bob"]))["updatedVersions"] == 3
    assert all(visible(client, bob, v["id"]) for v in (v1, v2, v3))
    assert not visible(client, bob, other["id"])


def test_share_does_not_touch_others_versions_in_same_question(client, alice, bob, db):
    """别人基于共享版本改出的版本属于别人：alice 改共享设置不影响 bob 的版本，反之亦然。"""
    carol = auth_headers_for(client, "carol")
    v1 = create(client, alice)
    ok(share(client, alice, v1["id"], ["bob"]))
    b2 = ok(derive(client, bob, v1["id"], title="bob 的版本"), 201)
    assert b2["sharing"] == {"public": False, "userIds": [], "usernames": []}  # 默认不共享

    assert ok(share(client, alice, v1["id"], ["bob", "carol"]))["updatedVersions"] == 1
    assert not visible(client, carol, b2["id"])
    # bob 可以单独共享自己的版本
    assert ok(share(client, bob, b2["id"], public=True))["updatedVersions"] == 1
    assert visible(client, carol, b2["id"])
    assert db[QUESTIONS].find_one({"_id": ObjectId(v1["id"])})["sharing"]["public"] is False


# ---------- 公开 ----------
def test_public_question(client, alice, bob):
    v1 = create(client, alice)
    ok(share(client, alice, v1["id"], public=True))
    pub = ok(client.get("/api/questions", params={"scope": "public"}, headers=bob))
    assert [i["id"] for i in pub["items"]] == [v1["id"]]
    assert visible(client, bob, v1["id"])


# ---------- 取消共享 ----------
def test_unshare(client, alice, bob):
    v1 = create(client, alice)
    ok(share(client, alice, v1["id"], ["bob"], public=True))
    b2 = ok(derive(client, bob, v1["id"], title="bob 的版本"), 201)
    ok(share(client, alice, v1["id"], [], public=False))
    assert not visible(client, bob, v1["id"])
    # bob 自己的版本仍在；历史中 alice 的版本变成占位节点
    assert visible(client, bob, b2["id"])
    h = ok(client.get(f"/api/questions/{b2['id']}/history", headers=bob))
    assert [n["accessible"] for n in h["versions"]] == [False, True]


def test_sharing_replaces_whole_setting(client, alice, bob):
    auth_headers_for(client, "carol")
    v1 = create(client, alice)
    ok(share(client, alice, v1["id"], ["bob", "carol"]))
    ok(share(client, alice, v1["id"], ["carol"]))
    assert not visible(client, bob, v1["id"])


# ---------- 继承 ----------
def test_new_versions_inherit_sharing(client, alice, bob):
    v1 = create(client, alice)
    ok(share(client, alice, v1["id"], ["bob"]))
    v2 = ok(derive(client, alice, v1["id"], title="v2"), 201)
    v3 = ok(client.post(f"/api/questions/{v1['id']}/restore", headers=alice), 201)
    assert v2["sharing"]["usernames"] == v3["sharing"]["usernames"] == ["bob"]
    assert visible(client, bob, v2["id"]) and visible(client, bob, v3["id"])


def test_concurrent_sharing_change_is_applied_to_new_version(client, alice, bob, monkeypatch):
    """派生时先读到旧的共享设置，插入前所有者恰好修改了共享：插入后与其他版本对齐，不会留下旧设置。"""
    from app.repositories import questions as repo
    v1 = create(client, alice)
    ok(share(client, alice, v1["id"], ["bob"]))
    real_insert = repo.insert

    def unshare_then_insert(db_, doc):
        # 模拟另一个请求：在新版本插入之前取消共享（updateMany 不包含尚未插入的新版本）
        repo.set_sharing_for_owner_in_root(db_, doc["rootId"], doc["ownerId"],
                                           {"public": False, "userIds": []})
        return real_insert(db_, doc)

    monkeypatch.setattr(repo, "insert", unshare_then_insert)
    v2 = ok(derive(client, alice, v1["id"], title="v2"), 201)
    monkeypatch.undo()
    assert v2["sharing"]["userIds"] == []
    assert not visible(client, bob, v2["id"])


# ---------- 权限 ----------
def test_only_owner_can_change_sharing(client, alice, bob):
    carol = auth_headers_for(client, "carol")
    v1 = create(client, alice)
    r = share(client, carol, v1["id"], ["carol"])
    assert r.status_code == 404                     # 看不到：与不存在一样
    ok(share(client, alice, v1["id"], ["bob"]))
    r = share(client, bob, v1["id"], ["carol"])
    assert r.status_code == 403 and r.json()["code"] == "NOT_OWNER"   # 看得到但不是自己的
    assert not visible(client, carol, v1["id"])


def test_shared_list_only_visible_to_owner(client, alice, bob):
    v1 = create(client, alice)
    ok(share(client, alice, v1["id"], ["bob"]))
    assert ok(client.get(f"/api/questions/{v1['id']}", headers=alice))["sharing"]["usernames"] == ["bob"]
    assert ok(client.get(f"/api/questions/{v1['id']}", headers=bob))["sharing"] is None
    listed = ok(client.get("/api/questions", params={"scope": "shared"}, headers=bob))["items"][0]
    assert listed["sharing"] is None
    node = ok(client.get(f"/api/questions/{v1['id']}/history", headers=bob))["versions"][0]
    assert node["detail"]["sharing"] is None


# ---------- 输入检查 ----------
def test_share_input_validation(client, alice, bob):
    v1 = create(client, alice)
    r = share(client, alice, v1["id"], ["nobody"])
    assert r.status_code == 422 and r.json()["errors"] == [
        {"field": "usernames[0]", "message": "用户「nobody」不存在"}]
    r = share(client, alice, v1["id"], ["bob", "alice"])
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "usernames[1]"
    r = client.put(f"/api/questions/{v1['id']}/sharing", json={"public": "yes", "usernames": []},
                   headers=alice)
    assert r.status_code == 422
    r = client.put(f"/api/questions/{v1['id']}/sharing", json={"public": True}, headers=alice)
    assert r.status_code == 422
    r = share(client, alice, v1["id"], [f"u{i}" for i in range(101)])
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "usernames"
    # 出错时不改动原设置
    assert ok(client.get(f"/api/questions/{v1['id']}", headers=alice))["sharing"]["userIds"] == []


def test_share_strips_and_dedups_usernames(client, alice, bob):
    v1 = create(client, alice)
    result = ok(share(client, alice, v1["id"], [" bob ", "bob"]))
    assert result["question"]["sharing"]["usernames"] == ["bob"]
    assert len(result["question"]["sharing"]["userIds"]) == 1


def test_sharing_does_not_change_updated_at(client, alice):
    """共享设置不是题目内容的修改：不改 updatedAt，不影响直接修改时的冲突检查。"""
    v1 = create(client, alice)
    ok(share(client, alice, v1["id"], public=True))
    after = ok(client.get(f"/api/questions/{v1['id']}", headers=alice))
    assert after["updatedAt"] == v1["updatedAt"]
    ok(client.put(f"/api/questions/{v1['id']}", json={**AGE, "title": "改"}, headers=alice,
                  params={"expectedUpdatedAt": v1["updatedAt"]}))
