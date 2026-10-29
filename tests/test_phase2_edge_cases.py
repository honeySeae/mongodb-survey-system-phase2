"""第二阶段第 11 步：补全测试——并发、数据异常和输入检查的边界情况（覆盖率检查中发现未测试的分支）。

单机 MongoDB 不使用事务，以下“同时发生”的情况用 monkeypatch 在两步之间插入另一个请求的效果来模拟。
"""
from bson import ObjectId

from app.db import QUESTION_BANKS, QUESTIONS, SURVEYS
from app.utils import now_utc
from tests.test_banks import add_item, bank, new_bank
from tests.test_question_library import AGE, GENDER, create, derive, ok
from tests.test_save_to_library import save
from tests.test_survey_library import add_lib, new_survey


# ---------- 直接修改版本：读取之后、写回之前发生了变化 ----------
def _patch_after_read(monkeypatch, action):
    """在 update_version 读取版本之后、条件更新之前执行 action（模拟另一个请求）。"""
    from app.repositories import questions as repo
    real = repo.used_option_ids

    def hook(db_, root_id):
        action(db_)
        return real(db_, root_id)

    monkeypatch.setattr(repo, "used_option_ids", hook)


def test_update_version_locked_meanwhile(client, alice, monkeypatch):
    v1 = create(client, alice)
    _patch_after_read(monkeypatch, lambda db_: db_[QUESTIONS].update_one(
        {"_id": ObjectId(v1["id"])}, {"$set": {"lockedAt": now_utc()}}))
    r = client.put(f"/api/questions/{v1['id']}", json={**AGE, "title": "改"}, headers=alice)
    assert r.status_code == 409 and r.json()["code"] == "QUESTION_LOCKED"
    monkeypatch.undo()
    assert ok(client.get(f"/api/questions/{v1['id']}", headers=alice))["title"] == AGE["title"]


def test_update_version_edited_meanwhile(client, alice, monkeypatch):
    v1 = create(client, alice)
    _patch_after_read(monkeypatch, lambda db_: db_[QUESTIONS].update_one(
        {"_id": ObjectId(v1["id"])}, {"$set": {"title": "另一个请求改的", "updatedAt": now_utc()}}))
    r = client.put(f"/api/questions/{v1['id']}", json={**AGE, "title": "改"}, headers=alice)
    assert r.status_code == 409 and r.json()["code"] == "EDIT_CONFLICT"
    monkeypatch.undo()
    assert ok(client.get(f"/api/questions/{v1['id']}", headers=alice))["title"] == "另一个请求改的"   # 不覆盖


def test_update_version_deleted_meanwhile(client, alice, monkeypatch):
    v1 = create(client, alice)
    _patch_after_read(monkeypatch, lambda db_: db_[QUESTIONS].delete_one({"_id": ObjectId(v1["id"])}))
    assert client.put(f"/api/questions/{v1['id']}", json={**AGE, "title": "改"}, headers=alice).status_code == 404


# ---------- 加锁、删除、版本号 ----------
def test_add_to_survey_when_version_deleted_meanwhile(client, alice, db, monkeypatch):
    """检查可访问之后、加锁之前版本被删除：返回 404，问卷不变。"""
    from app.repositories import questions as repo
    v1 = create(client, alice)
    sid = new_survey(client, alice)["id"]
    real = repo.lock

    def deleted_then_lock(db_, qid, now):
        db_[QUESTIONS].delete_one({"_id": qid})
        return real(db_, qid, now)

    monkeypatch.setattr(repo, "lock", deleted_then_lock)
    assert add_lib(client, alice, sid, v1["id"]).status_code == 404
    assert db[SURVEYS].find_one({"_id": ObjectId(sid)})["questions"] == []


def test_delete_version_locked_after_check(client, alice, monkeypatch):
    """删除前的检查通过之后，版本恰好被加进问卷（加锁）：删除失败，返回 409，版本保留。"""
    from app.repositories import questions as repo
    v1 = create(client, alice)
    real = repo.in_any_bank

    def then_locked(db_, qid):
        db_[QUESTIONS].update_one({"_id": qid}, {"$set": {"lockedAt": now_utc()}})
        return real(db_, qid)

    monkeypatch.setattr(repo, "in_any_bank", then_locked)
    r = client.delete(f"/api/questions/{v1['id']}", headers=alice)
    assert r.status_code == 409 and r.json()["code"] == "QUESTION_LOCKED"
    monkeypatch.undo()
    assert ok(client.get(f"/api/questions/{v1['id']}", headers=alice))["locked"] is True


def test_version_number_retries_exhausted(client, alice, monkeypatch):
    """版本号连续冲突超过重试次数：返回 409 VERSION_CONFLICT，不插入任何版本。"""
    from app.repositories import questions as repo
    v1 = create(client, alice)
    monkeypatch.setattr(repo, "max_version", lambda db_, root: 0)   # 总是取到已被占用的版本号 1
    r = derive(client, alice, v1["id"], title="v2")
    assert r.status_code == 409 and r.json()["code"] == "VERSION_CONFLICT"
    monkeypatch.undo()
    assert [i["version"] for i in ok(client.get("/api/questions", headers=alice))["items"]] == [1]


def test_list_with_malformed_root_id(client, alice):
    create(client, alice)
    data = ok(client.get("/api/questions", params={"rootId": "not-an-id"}, headers=alice))
    assert data == {"items": [], "total": 0, "offset": 0, "limit": 20}


# ---------- 存入“我的题目”：期间问卷中的题被删除 ----------
def test_save_to_library_question_deleted_meanwhile(client, alice, db, monkeypatch):
    from app.services import question_library as library
    sid = new_survey(client, alice)["id"]
    q = ok(client.post(f"/api/surveys/{sid}/questions", json={"type": "text", "title": "备注"}, headers=alice), 201)
    qid = q["questions"][0]["id"]
    real = library.create_from_survey_question

    def then_question_deleted(db_, owner_id, question):
        doc = real(db_, owner_id, question)
        db_[SURVEYS].update_one({"_id": ObjectId(sid)}, {"$set": {"questions": [], "updatedAt": now_utc()}})
        return doc

    monkeypatch.setattr(library, "create_from_survey_question", then_question_deleted)
    assert save(client, alice, sid, qid).status_code == 404
    assert db[QUESTIONS].count_documents({}) == 0          # 撤销了刚创建的 v1


# ---------- 题库 ----------
def test_update_bank_validation_and_no_change(client, alice):
    b = new_bank(client, alice)
    r = client.patch(f"/api/banks/{b['id']}", json={"name": "  "}, headers=alice)
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "name"
    r = client.patch(f"/api/banks/{b['id']}", json={"description": "x" * 1001}, headers=alice)
    assert r.status_code == 422
    same = ok(client.patch(f"/api/banks/{b['id']}", json={}, headers=alice))   # 没有要改的字段：原样返回
    assert same["updatedAt"] == b["updatedAt"] and same["name"] == b["name"]


def test_add_item_when_bank_deleted_meanwhile(client, alice, db, monkeypatch):
    from app.repositories import banks as banks_repo
    v1 = create(client, alice)
    b = new_bank(client, alice)
    real = banks_repo.update_owned

    def bank_deleted_first(db_, bank_id, owner_id, update, extra_filter=None):
        db_[QUESTION_BANKS].delete_one({"_id": bank_id})
        return real(db_, bank_id, owner_id, update, extra_filter)

    monkeypatch.setattr(banks_repo, "update_owned", bank_deleted_first)
    r = add_item(client, alice, b["id"], v1["id"])
    assert r.status_code == 404 and r.json()["code"] == "BANK_NOT_FOUND"


def test_bank_item_whose_version_no_longer_exists(client, alice, db):
    """数据异常（版本被绕过接口删除）：题库中这一项显示不可用，并说明“这个版本已不存在”。"""
    v1 = create(client, alice, GENDER)
    b = new_bank(client, alice)
    ok(add_item(client, alice, b["id"], v1["id"]), 201)
    db[QUESTIONS].delete_one({"_id": ObjectId(v1["id"])})
    item = ok(bank(client, alice, b["id"]))["items"][0]
    assert item["available"] is False and item["notice"] == "这个版本已不存在；请移除这一项"
