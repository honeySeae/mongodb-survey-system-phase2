"""第二阶段第 3 步：版本内容规则与访问权限（纯函数，设计文档 10.4、10.9）。"""
from bson import ObjectId

from app.logic import question_access as access
from app.logic.question_versions import build_content, new_option_id


def base_choice():
    return {"type": "single_choice", "title": "性别",
            "options": [{"id": "o_aaa111", "text": "男"}, {"id": "o_bbb222", "text": "女"}],
            "validation": {}}


def fields(problems):
    return [p["field"] for p in problems]


# ---------- 新建 ----------
def test_new_question_generates_option_ids():
    used = set()
    content, problems = build_content(qtype="multiple_choice", title=" 爱好 ",
                                      options=[{"text": " 读书 "}, {"text": "运动"}],
                                      validation={"minSelect": 1, "maxSelect": 2}, used_option_ids=used)
    assert problems == []
    assert content["title"] == "爱好"
    assert [o["text"] for o in content["options"]] == ["读书", "运动"]
    assert all(o["id"].startswith("o_") and len(o["id"]) == 8 for o in content["options"])
    assert used == {o["id"] for o in content["options"]}
    assert "required" not in content["validation"]


def test_required_not_allowed_in_question_version():
    _, problems = build_content(qtype="text", title="建议", options=None,
                                validation={"required": True, "maxLength": 100})
    assert fields(problems) == ["validation.required"]


def test_phase1_content_rules_reused():
    """内容检查复用第一阶段 question_rules：非法题型、字段与题型不匹配、min > max 都拒绝。"""
    assert fields(build_content(qtype="rating", title="t", options=None, validation=None)[1]) == ["type"]
    assert "validation.minLength" in fields(
        build_content(qtype="number", title="年龄", options=None, validation={"minLength": 1})[1])
    assert "validation.min" in fields(
        build_content(qtype="number", title="年龄", options=None, validation={"min": 5, "max": 1})[1])
    assert "options" in fields(
        build_content(qtype="text", title="建议", options=[{"text": "a"}], validation=None)[1])


# ---------- 基于原版本修改 ----------
def test_type_cannot_change():
    _, problems = build_content(qtype="multiple_choice", title="性别", options=[{"text": "男"}],
                                validation=None, base=base_choice())
    assert fields(problems) == ["type"]


def test_kept_options_keep_ids_new_options_get_new_ids():
    used = {"o_aaa111", "o_bbb222", "o_old999"}   # o_old999：更早的版本中删掉的选项
    content, problems = build_content(
        qtype="single_choice", title="性别",
        options=[{"id": "o_bbb222", "text": "女性"}, {"text": "不愿透露"}],  # 改了文字、删了“男”、加了一项
        validation=None, base=base_choice(), used_option_ids=used)
    assert problems == []
    ids = [o["id"] for o in content["options"]]
    assert ids[0] == "o_bbb222"                       # 只改文字，id 不变
    assert ids[1] not in {"o_aaa111", "o_bbb222", "o_old999"}  # 新 id 不与这道题任何版本用过的 id 重复
    assert content["options"][0]["text"] == "女性"


def test_option_id_must_belong_to_base_version():
    _, problems = build_content(qtype="single_choice", title="性别",
                                options=[{"id": "o_zzz000", "text": "男"}], validation=None,
                                base=base_choice())
    assert fields(problems) == ["options[0].id"]


def test_option_id_cannot_repeat():
    _, problems = build_content(qtype="single_choice", title="性别",
                                options=[{"id": "o_aaa111", "text": "男"}, {"id": "o_aaa111", "text": "男2"}],
                                validation=None, base=base_choice())
    assert fields(problems) == ["options[1].id"]


def test_new_option_id_avoids_used():
    used = {"o_aaaaaa"}
    oid = new_option_id(used)
    assert oid != "o_aaaaaa" and oid in used


# ---------- 访问权限 ----------
def version(owner, public=False, user_ids=(), locked=False):
    return {"_id": ObjectId(), "ownerId": owner,
            "sharing": {"public": public, "userIds": list(user_ids)},
            "lockedAt": object() if locked else None}


def test_access_rules():
    alice, bob, carol = ObjectId(), ObjectId(), ObjectId()
    private = version(alice)
    shared = version(alice, user_ids=[bob])
    public = version(alice, public=True)
    assert access.can_access(private, alice) and not access.can_access(private, bob)
    assert access.can_access(shared, bob) and not access.can_access(shared, carol)
    assert access.can_access(public, carol)
    # 第 4 条（题库）由调用方传入
    assert access.can_access(private, bob, bank_granted={private["_id"]})
    assert access.is_owner(shared, alice) and not access.is_owner(shared, bob)


def test_locked():
    assert access.is_locked(version(ObjectId(), locked=True))
    assert not access.is_locked(version(ObjectId()))
    assert not access.is_locked({"ownerId": ObjectId()})  # 没有 lockedAt 字段也算未锁定
