"""第二阶段第 7 步：题库（设计文档 10.7、10.9）。

- 题库的增删改、条目的加入 / 移除 / 换版本；同一道题只能有一项；放进题库不锁定版本
- 加入的版本必须是创建者直接可访问的；只有创建者能修改题库
- 共享题库：别人可以查看、使用（选进自己的问卷）、基于其中的版本派生，不能修改
- 条目是否可用实时判断：原作者取消共享后，这一项对所有人不可用，已复制进问卷的题不受影响
"""
from bson import ObjectId

from app.db import QUESTION_BANKS, QUESTIONS
from app.utils import now_utc
from tests.conftest import auth_headers_for
from tests.test_question_library import AGE, GENDER, create, derive, ok
from tests.test_question_sharing import share
from tests.test_survey_library import add_lib, locked, new_survey


def new_bank(client, headers, name="学生基本信息", **body):
    return ok(client.post("/api/banks", json={"name": name, **body}, headers=headers), 201)


def add_item(client, headers, bid, qid):
    return client.post(f"/api/banks/{bid}/items", json={"questionId": qid}, headers=headers)


def bank(client, headers, bid):
    return client.get(f"/api/banks/{bid}", headers=headers)


def share_bank(client, headers, bid, usernames=(), public=False):
    return client.put(f"/api/banks/{bid}/sharing", json={"public": public, "usernames": list(usernames)},
                      headers=headers)


def visible(client, headers, qid) -> bool:
    return client.get(f"/api/questions/{qid}", headers=headers).status_code == 200


# ---------- 题库本身 ----------
def test_create_and_update_bank(client, alice):
    b = new_bank(client, alice, name="  常用题  ", description="每学期都用")
    assert (b["name"], b["description"], b["owner"], b["isMine"]) == ("常用题", "每学期都用", "alice", True)
    assert b["items"] == [] and b["itemCount"] == 0
    assert b["sharing"] == {"public": False, "userIds": [], "usernames": []}
    b2 = ok(client.patch(f"/api/banks/{b['id']}", json={"description": "改了说明"}, headers=alice))
    assert b2["name"] == "常用题" and b2["description"] == "改了说明"
    assert b2["updatedAt"] > b["updatedAt"]


def test_bank_input_validation(client, alice):
    assert client.post("/api/banks", json={"name": "  "}, headers=alice).status_code == 422
    assert client.post("/api/banks", json={"name": "x" * 101}, headers=alice).status_code == 422
    assert client.post("/api/banks", json={"name": "a", "description": "x" * 1001}, headers=alice).status_code == 422
    assert client.post("/api/banks", json={"name": "a", "extra": 1}, headers=alice).status_code == 422
    assert client.post("/api/banks", json={"name": "a"}).status_code == 401


def test_list_banks_scopes(client, alice, bob):
    a1 = new_bank(client, alice, name="A1")
    a2 = new_bank(client, alice, name="A2")
    ok(share_bank(client, alice, a1["id"], ["bob"]))
    ok(share_bank(client, alice, a2["id"], public=True))
    b1 = new_bank(client, bob, name="B1")
    ok(add_item(client, bob, b1["id"], create(client, bob)["id"]), 201)

    def names(scope):
        data = ok(client.get("/api/banks", params={"scope": scope}, headers=bob))
        return {i["name"]: i["itemCount"] for i in data["items"]}

    assert names("mine") == {"B1": 1}
    assert names("shared") == {"A1": 0}
    assert names("public") == {"A2": 0}
    assert names("all") == {"A1": 0, "A2": 0, "B1": 1}


def test_delete_bank_does_not_affect_surveys_or_versions(client, alice):
    v1 = create(client, alice)
    b = new_bank(client, alice)
    ok(add_item(client, alice, b["id"], v1["id"]), 201)
    sid = new_survey(client, alice)["id"]
    ok(add_lib(client, alice, sid, v1["id"]), 201)
    assert client.delete(f"/api/banks/{b['id']}", headers=alice).status_code == 204
    assert bank(client, alice, b["id"]).status_code == 404
    assert ok(client.get(f"/api/surveys/{sid}", headers=alice))["questions"][0]["title"] == "你的年龄"
    assert visible(client, alice, v1["id"])


# ---------- 条目 ----------
def test_add_items(client, alice, db):
    v1 = create(client, alice)
    g1 = create(client, alice, GENDER)
    b = new_bank(client, alice)
    ok(add_item(client, alice, b["id"], v1["id"]), 201)
    b = ok(add_item(client, alice, b["id"], g1["id"]), 201)
    assert [(i["questionId"], i["rootId"], i["available"]) for i in b["items"]] == [
        (v1["id"], v1["rootId"], True), (g1["id"], g1["rootId"], True)]
    assert b["items"][0]["question"]["title"] == "你的年龄"
    assert not locked(client, alice, v1["id"])          # 放进题库不算用过


def test_one_item_per_question(client, alice):
    v1 = create(client, alice)
    v2 = ok(derive(client, alice, v1["id"], title="v2"), 201)
    b = new_bank(client, alice)
    ok(add_item(client, alice, b["id"], v1["id"]), 201)
    for qid in (v1["id"], v2["id"]):
        r = add_item(client, alice, b["id"], qid)
        assert r.status_code == 409 and r.json()["code"] == "ALREADY_IN_BANK"


def test_switch_item_version(client, alice):
    """需求七：题库里的题可以更新版本（由创建者手动更换，不自动跟随）。"""
    v1 = create(client, alice)
    v2 = ok(derive(client, alice, v1["id"], title="新问法"), 201)
    other = create(client, alice, GENDER)
    b = new_bank(client, alice)
    ok(add_item(client, alice, b["id"], v1["id"]), 201)
    ok(derive(client, alice, v1["id"], title="v3"), 201)
    assert ok(bank(client, alice, b["id"]))["items"][0]["questionId"] == v1["id"]   # 不自动跟随

    url = f"/api/banks/{b['id']}/items/{v1['rootId']}"
    b2 = ok(client.put(url, json={"questionId": v2["id"]}, headers=alice))
    assert b2["items"][0]["questionId"] == v2["id"] and b2["items"][0]["question"]["title"] == "新问法"
    r = client.put(url, json={"questionId": other["id"]}, headers=alice)     # 另一道题
    assert r.status_code == 422
    assert ok(client.put(url, json={"questionId": v2["id"]}, headers=alice))["items"][0]["questionId"] == v2["id"]
    r = client.put(f"/api/banks/{b['id']}/items/{other['rootId']}", json={"questionId": other["id"]},
                   headers=alice)
    assert r.status_code == 404 and r.json()["code"] == "ITEM_NOT_FOUND"


def test_remove_item(client, alice):
    v1 = create(client, alice)
    b = new_bank(client, alice)
    ok(add_item(client, alice, b["id"], v1["id"]), 201)
    b2 = ok(client.delete(f"/api/banks/{b['id']}/items/{v1['rootId']}", headers=alice))
    assert b2["items"] == []
    assert client.delete(f"/api/banks/{b['id']}/items/{v1['rootId']}", headers=alice).status_code == 404
    assert client.delete(f"/api/banks/{b['id']}/items/not-an-id", headers=alice).status_code == 404
    # 移出题库后版本可以删除
    assert client.delete(f"/api/questions/{v1['id']}", headers=alice).status_code == 204


def test_version_in_bank_cannot_be_deleted(client, alice, bob):
    """删除不能影响别人的题库：版本在任何人的题库中都不能删。"""
    v1 = create(client, alice)
    ok(share(client, alice, v1["id"], ["bob"]))
    b = new_bank(client, bob)
    ok(add_item(client, bob, b["id"], v1["id"]), 201)
    r = client.delete(f"/api/questions/{v1['id']}", headers=alice)
    assert r.status_code == 409 and r.json()["code"] == "QUESTION_IN_BANK"


def test_items_limit(client, alice, db):
    b = new_bank(client, alice)
    db[QUESTION_BANKS].update_one({"_id": ObjectId(b["id"])}, {"$set": {"items": [
        {"questionId": ObjectId(), "rootId": ObjectId(), "addedAt": now_utc()} for _ in range(200)]}})
    r = add_item(client, alice, b["id"], create(client, alice)["id"])
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "items"


def test_which_versions_can_be_added(client, alice, bob):
    carol = auth_headers_for(client, "carol")
    private = create(client, carol)
    shared = create(client, carol, GENDER)
    ok(share(client, carol, shared["id"], ["alice"]))
    b = new_bank(client, alice)
    assert add_item(client, alice, b["id"], private["id"]).status_code == 404   # 看不到
    ok(add_item(client, alice, b["id"], shared["id"]), 201)                      # 共享给自己的可以

    # bob 只能通过 alice 的题库看到 carol 的题：不能再加入自己的题库（避免题库套题库）
    ok(share_bank(client, alice, b["id"], ["bob"]))
    assert visible(client, bob, shared["id"])
    bob_bank = new_bank(client, bob)
    r = add_item(client, bob, bob_bank["id"], shared["id"])
    assert r.status_code == 403 and r.json()["code"] == "NOT_DIRECTLY_ACCESSIBLE"


# ---------- 权限 ----------
def test_only_owner_modifies_bank(client, alice, bob):
    carol = auth_headers_for(client, "carol")
    v1 = create(client, alice)
    b = new_bank(client, alice)
    ok(add_item(client, alice, b["id"], v1["id"]), 201)
    ok(share_bank(client, alice, b["id"], ["bob"]))
    bid, root = b["id"], v1["rootId"]
    attempts = {
        "patch": lambda h: client.patch(f"/api/banks/{bid}", json={"name": "x"}, headers=h),
        "delete": lambda h: client.delete(f"/api/banks/{bid}", headers=h),
        "share": lambda h: share_bank(client, h, bid, public=True),
        "add": lambda h: add_item(client, h, bid, create(client, h, GENDER)["id"]),
        "switch": lambda h: client.put(f"/api/banks/{bid}/items/{root}", json={"questionId": v1["id"]}, headers=h),
        "remove": lambda h: client.delete(f"/api/banks/{bid}/items/{root}", headers=h),
    }
    for name, attempt in attempts.items():
        r = attempt(bob)                       # 共享给 bob：看得到，不能改
        assert r.status_code == 403 and r.json()["code"] == "NOT_OWNER", name
        assert attempt(carol).status_code == 404, name   # 看不到：与不存在一样
    assert bank(client, carol, bid).status_code == 404
    assert bank(client, bob, str(ObjectId())).status_code == 404
    after = ok(bank(client, alice, bid))
    assert after["name"] == "学生基本信息" and len(after["items"]) == 1


def test_bank_sharing_list_only_for_owner(client, alice, bob):
    b = new_bank(client, alice)
    ok(share_bank(client, alice, b["id"], ["bob"]))
    assert ok(bank(client, alice, b["id"]))["sharing"]["usernames"] == ["bob"]
    seen = ok(bank(client, bob, b["id"]))
    assert seen["sharing"] is None and seen["isMine"] is False and seen["owner"] == "alice"
    assert ok(client.get("/api/banks", params={"scope": "shared"}, headers=bob))["items"][0]["sharing"] is None
    r = share_bank(client, alice, b["id"], ["nobody"])
    assert r.status_code == 422


# ---------- 共享题库：使用、派生 ----------
def test_shared_bank_grants_use_and_derive(client, alice, bob):
    """需求七：做问卷时直接从题库选题。alice 的题没有单独共享，bob 通过共享的题库使用。"""
    v1 = create(client, alice)
    b = new_bank(client, alice)
    ok(add_item(client, alice, b["id"], v1["id"]), 201)
    assert not visible(client, bob, v1["id"])
    ok(share_bank(client, alice, b["id"], ["bob"]))

    item = ok(bank(client, bob, b["id"]))["items"][0]
    assert item["available"] and item["question"]["title"] == "你的年龄"
    assert item["question"]["sharing"] is None            # 题目的共享名单也不暴露
    assert visible(client, bob, v1["id"])
    # 选进 bob 自己的问卷
    sid = new_survey(client, bob)["id"]
    s = ok(add_lib(client, bob, sid, item["questionId"], required=True), 201)
    assert s["questions"][0]["source"]["questionId"] == v1["id"]
    # 基于它派生自己的版本；不能直接修改
    mine = ok(derive(client, bob, v1["id"], title="bob 的问法"), 201)
    assert mine["owner"] == "bob"
    r = client.put(f"/api/questions/{v1['id']}", json={**AGE, "title": "x"}, headers=bob)
    assert r.status_code == 403                          # 先检查所有者（虽然也已被问卷使用）
    # 历史中通过题库获得访问权的版本可见
    h = ok(client.get(f"/api/questions/{mine['id']}/history", headers=bob))
    assert [n["accessible"] for n in h["versions"]] == [True, True]


def test_public_bank(client, alice, bob):
    v1 = create(client, alice)
    b = new_bank(client, alice)
    ok(add_item(client, alice, b["id"], v1["id"]), 201)
    ok(share_bank(client, alice, b["id"], public=True))
    assert visible(client, bob, v1["id"])
    ok(share_bank(client, alice, b["id"], public=False))
    assert not visible(client, bob, v1["id"])             # 取消共享题库后不再能访问
    assert bank(client, bob, b["id"]).status_code == 404


def test_only_items_of_the_bank_are_granted(client, alice, bob):
    v1 = create(client, alice)
    v2 = ok(derive(client, alice, v1["id"], title="v2"), 201)
    b = new_bank(client, alice)
    ok(add_item(client, alice, b["id"], v1["id"]), 201)
    ok(share_bank(client, alice, b["id"], ["bob"]))
    assert visible(client, bob, v1["id"]) and not visible(client, bob, v2["id"])
    h = ok(client.get(f"/api/questions/{v1['id']}/history", headers=bob))
    assert [n["accessible"] for n in h["versions"]] == [True, False]
    # 换版本后，访问权随之转移
    ok(client.put(f"/api/banks/{b['id']}/items/{v1['rootId']}", json={"questionId": v2["id"]}, headers=alice))
    assert visible(client, bob, v2["id"]) and not visible(client, bob, v1["id"])


# ---------- 实时判断可用性 ----------
def test_item_unavailable_after_original_owner_unshares(client, alice, bob):
    """alice 的公开题库里有 carol 共享给 alice 的题；carol 取消共享后，这一项对所有人不可用，
    已经复制进 bob 问卷的题不受影响。"""
    carol = auth_headers_for(client, "carol")
    c1 = create(client, carol)
    ok(share(client, carol, c1["id"], ["alice"]))
    b = new_bank(client, alice)
    ok(add_item(client, alice, b["id"], c1["id"]), 201)
    ok(share_bank(client, alice, b["id"], public=True))
    sid = new_survey(client, bob)["id"]
    ok(add_lib(client, bob, sid, c1["id"]), 201)

    ok(share(client, carol, c1["id"], []))
    for headers in (alice, bob):
        item = ok(bank(client, headers, b["id"]))["items"][0]
        assert {k: item[k] for k in ("questionId", "rootId", "available", "question")} == {
            "questionId": c1["id"], "rootId": c1["rootId"], "available": False, "question": None}
        assert not visible(client, headers, c1["id"])
    # 只对题库创建者说明原因；其他人只看到不可用
    assert "carol 已取消共享" in ok(bank(client, alice, b["id"]))["items"][0]["notice"]
    bob_item = ok(bank(client, bob, b["id"]))["items"][0]
    assert bob_item["notice"] is None and bob_item["newerVersion"] is None
    assert ok(bank(client, alice, b["id"]))["itemCount"] == 1          # 条目保留
    assert ok(client.get(f"/api/surveys/{sid}", headers=bob))["questions"][0]["title"] == "你的年龄"
    # carol 重新共享后恢复可用
    ok(share(client, carol, c1["id"], ["alice"]))
    assert ok(bank(client, bob, b["id"]))["items"][0]["available"] is True


# ---------- 并发 ----------
def test_add_item_undone_if_version_deleted_concurrently(client, alice, db, monkeypatch):
    """加入题库时版本恰好被删除：撤销这一项并返回 404，题库中不留下指向不存在版本的条目。"""
    from app.services import banks as bank_service
    v1 = create(client, alice)
    b = new_bank(client, alice)
    real = bank_service._version_for_item

    def then_deleted(db_, user_id, question_id):
        doc = real(db_, user_id, question_id)
        db_[QUESTIONS].delete_one({"_id": doc["_id"]})   # 另一个请求：删除检查已通过（当时不在题库中）
        return doc

    monkeypatch.setattr(bank_service, "_version_for_item", then_deleted)
    r = add_item(client, alice, b["id"], v1["id"])
    assert r.status_code == 404
    assert db[QUESTION_BANKS].find_one({"_id": ObjectId(b["id"])})["items"] == []


def test_switch_item_undone_if_version_deleted_concurrently(client, alice, db, monkeypatch):
    from app.services import banks as bank_service
    v1 = create(client, alice)
    v2 = ok(derive(client, alice, v1["id"], title="v2"), 201)
    b = new_bank(client, alice)
    ok(add_item(client, alice, b["id"], v1["id"]), 201)
    real = bank_service._version_for_item

    def then_deleted(db_, user_id, question_id):
        doc = real(db_, user_id, question_id)
        db_[QUESTIONS].delete_one({"_id": doc["_id"]})
        return doc

    monkeypatch.setattr(bank_service, "_version_for_item", then_deleted)
    r = client.put(f"/api/banks/{b['id']}/items/{v1['rootId']}", json={"questionId": v2["id"]}, headers=alice)
    assert r.status_code == 404
    items = db[QUESTION_BANKS].find_one({"_id": ObjectId(b["id"])})["items"]
    assert [i["questionId"] for i in items] == [ObjectId(v1["id"])]   # 恢复为原来的版本


# ---------- 给题库创建者的提示：有新版本可换、不可用的原因 ----------
def item_of(client, headers, bid, index=0):
    return ok(bank(client, headers, bid))["items"][index]


def test_hint_newer_version(client, alice, bob):
    v1 = create(client, alice)
    b = new_bank(client, alice)
    ok(add_item(client, alice, b["id"], v1["id"]), 201)
    item = item_of(client, alice, b["id"])
    assert item["newerVersion"] is None and item["notice"] is None      # 没有新版本时不提示

    ok(derive(client, alice, v1["id"], title="v2"), 201)
    v3 = ok(derive(client, alice, v1["id"], title="v3"), 201)
    item = item_of(client, alice, b["id"])
    assert item["newerVersion"] == {"questionId": v3["id"], "version": 3}   # 提示最新的
    assert item["notice"] == "有新版本 v3 可换"

    # 换成 v3 后不再提示
    ok(client.put(f"/api/banks/{b['id']}/items/{v1['rootId']}", json={"questionId": v3["id"]}, headers=alice))
    item = item_of(client, alice, b["id"])
    assert item["newerVersion"] is None and item["notice"] is None

    # 其他人看不到提示
    ok(share_bank(client, alice, b["id"], ["bob"]))
    ok(client.put(f"/api/banks/{b['id']}/items/{v1['rootId']}", json={"questionId": v1["id"]}, headers=alice))
    other = item_of(client, bob, b["id"])
    assert other["available"] and other["newerVersion"] is None and other["notice"] is None


def test_hint_only_versions_owner_can_use(client, alice, bob):
    """只提示题库创建者能直接访问的新版本：别人未共享的派生版本不算；别人共享的算。"""
    v1 = create(client, alice)
    ok(share(client, alice, v1["id"], ["bob"]))
    b = new_bank(client, alice)
    ok(add_item(client, alice, b["id"], v1["id"]), 201)
    b2 = ok(derive(client, bob, v1["id"], title="bob 的版本"), 201)       # bob 的版本，默认不共享
    assert item_of(client, alice, b["id"])["newerVersion"] is None
    ok(share(client, bob, b2["id"], ["alice"]))
    assert item_of(client, alice, b["id"])["newerVersion"] == {"questionId": b2["id"], "version": 2}


def test_hint_ignores_older_versions(client, alice):
    """当前项已是较新的版本时，旧版本不算“新版本”。"""
    v1 = create(client, alice)
    v2 = ok(derive(client, alice, v1["id"], title="v2"), 201)
    b = new_bank(client, alice)
    ok(add_item(client, alice, b["id"], v2["id"]), 201)
    assert item_of(client, alice, b["id"])["newerVersion"] is None


def test_unavailable_notice_suggests_replacement(client, alice):
    """原作者取消共享后：提示原因；若创建者有这道题的其他可用版本（如自己派生的），建议换成它。"""
    carol = auth_headers_for(client, "carol")
    c1 = create(client, carol)
    ok(share(client, carol, c1["id"], ["alice"]))
    b = new_bank(client, alice)
    ok(add_item(client, alice, b["id"], c1["id"]), 201)
    ok(share(client, carol, c1["id"], []))
    item = item_of(client, alice, b["id"])
    assert item["available"] is False and item["newerVersion"] is None
    assert item["notice"] == "原作者 carol 已取消共享（或不再公开）这道题，你已不能使用这个版本；请移除这一项"

    # 取消共享前 alice 派生了自己的版本：建议换成它（即使当前项不可用，也只能换同一道题的版本）
    ok(share(client, carol, c1["id"], ["alice"]))
    mine = ok(derive(client, alice, c1["id"], title="alice 的版本"), 201)
    ok(share(client, carol, c1["id"], []))
    item = item_of(client, alice, b["id"])
    assert item["newerVersion"] == {"questionId": mine["id"], "version": 2}
    assert item["notice"].endswith("请移除这一项，或换成 v2")
    ok(client.put(f"/api/banks/{b['id']}/items/{c1['rootId']}", json={"questionId": mine["id"]}, headers=alice))
    item = item_of(client, alice, b["id"])
    assert item["available"] and item["notice"] is None
