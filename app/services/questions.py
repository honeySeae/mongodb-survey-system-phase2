"""题目编辑的业务逻辑：添加、修改、删除、调整顺序。

约定（2026-10-19 开发者确认，见 AI_LOG 第 16 条、设计文档 6.3 第 9~11 条）：
- 只有草稿可以修改题目
- 每次修改后对整份问卷做一次检查（app/logic/survey_check.py），不合法则拒绝本次修改
- 添加题目时不接受跳转规则；修改题目时整体替换，保留的选项带原 id
- 写回时带上读取时的 updatedAt 做条件更新，防止并发修改互相覆盖；
  请求可选带 expectedUpdatedAt，带了就与当前值比较

第二阶段（设计文档 10.3、10.5）：
- 题目可以带 source（来自题目库的某个版本）。没有 source 的题（第一阶段的题、在问卷中直接新建的题）
  所有行为与第一阶段完全相同
- 有 source 的题：内容和校验是来源版本的副本，修改题目时只能改 validation.required 和跳转规则
- 从题目库添加、换版本：先给版本加锁再复制；同一道题（同一 rootId）在一份问卷中只能出现一次；
  副本沿用来源版本的选项 id，与问卷中其他 id 重复时拒绝
"""
import copy
import secrets
import string
from datetime import datetime, timedelta

from bson import ObjectId
from pymongo.database import Database

from app.errors import Conflict, NotFound, ValidationFailed
from app.logic import survey_state as state
from app.logic.survey_check import MAX_QUESTIONS, check_survey, find_references
from app.repositories import surveys as surveys_repo
from app.services import question_library as library
from app.services.surveys import get_owned
from app.utils import now_utc, to_mongo_time

ID_ALPHABET = string.ascii_lowercase + string.digits
ID_LENGTH = 6


def new_id(prefix: str, used: set[str]) -> str:
    """生成问卷内唯一的 id（如 q_k3x9ab、o_a1b2c3），并加入 used。"""
    while True:
        candidate = prefix + "".join(secrets.choice(ID_ALPHABET) for _ in range(ID_LENGTH))
        if candidate not in used:
            used.add(candidate)
            return candidate


def _used_ids(questions: list[dict]) -> set[str]:
    used = set()
    for q in questions:
        used.add(q["id"])
        used.update(o["id"] for o in q.get("options") or [])
    return used


def _edit_conflict() -> Conflict:
    return Conflict("EDIT_CONFLICT", "问卷已被修改，请刷新后重试")


def _load_editable(db: Database, owner_id: ObjectId, survey_id: str,
                   expected_updated_at: datetime | None) -> dict:
    survey = get_owned(db, owner_id, survey_id)
    if not state.can(survey["status"], "edit_questions"):
        raise Conflict("INVALID_STATUS",
                       f"问卷{state.STATUS_NAMES[survey['status']]}，不能修改题目")
    if expected_updated_at is not None and to_mongo_time(expected_updated_at) != survey["updatedAt"]:
        raise _edit_conflict()
    return survey


def _save(db: Database, owner_id: ObjectId, survey: dict, questions: list[dict]) -> dict:
    """整体检查后写回题目数组。"""
    result = check_survey(questions)
    if not result.ok:
        raise ValidationFailed(result.errors, "题目设置不合法")
    # 新的 updatedAt 必须严格大于旧值，否则同一毫秒内的两次修改无法区分
    now = max(now_utc(), survey["updatedAt"] + timedelta(milliseconds=1))
    updated = surveys_repo.update_if_status(
        db, survey["_id"], owner_id, state.DRAFT,
        {"questions": questions, "updatedAt": now},
        extra_filter={"updatedAt": survey["updatedAt"]},
    )
    if updated is None:
        raise _edit_conflict()
    return updated


def _find_index(survey: dict, question_id: str) -> int:
    for i, q in enumerate(survey["questions"]):
        if q["id"] == question_id:
            return i
    raise NotFound("QUESTION_NOT_FOUND", "题目不存在")


def _normalize_validation(validation: dict | None) -> dict:
    v = dict(validation or {})
    v.setdefault("required", False)
    return v


# ---------- 添加 ----------
def add_question(db: Database, owner_id: ObjectId, survey_id: str, *, qtype: str, title: str,
                 options: list[dict] | None, validation: dict | None, position: int | None,
                 logic_given: bool, expected_updated_at: datetime | None = None) -> dict:
    survey = _load_editable(db, owner_id, survey_id, expected_updated_at)
    if logic_given:
        raise ValidationFailed([{"field": "logic",
                                 "message": "添加题目时不能设置跳转规则，请添加后通过修改题目设置"}])
    questions = list(survey["questions"])
    if position is not None and not 1 <= position <= len(questions) + 1:
        raise ValidationFailed([{"field": "position",
                                 "message": f"position 应为 1~{len(questions) + 1}"}])

    used = _used_ids(questions)
    question = {"id": new_id("q_", used), "type": qtype, "title": title.strip()}
    if options is not None:
        question["options"] = [{"id": new_id("o_", used), "text": o["text"].strip()} for o in options]
    question["validation"] = _normalize_validation(validation)

    index = len(questions) if position is None else position - 1
    questions.insert(index, question)
    return _save(db, owner_id, survey, questions)


# ---------- 修改 ----------
def update_question(db: Database, owner_id: ObjectId, survey_id: str, question_id: str, *,
                    qtype: str, title: str, options: list[dict] | None, validation: dict | None,
                    logic: dict | None, expected_updated_at: datetime | None = None) -> dict:
    survey = _load_editable(db, owner_id, survey_id, expected_updated_at)
    questions = list(survey["questions"])
    i = _find_index(survey, question_id)
    old_option_ids = {o["id"] for o in questions[i].get("options") or []}

    used = _used_ids(questions)
    question = {"id": question_id, "type": qtype, "title": title.strip()}
    if options is not None:
        new_options, errors, kept = [], [], set()
        for k, o in enumerate(options):
            oid = o.get("id")
            if oid is None:
                oid = new_id("o_", used)
            elif oid not in old_option_ids or oid in kept:
                errors.append({"field": f"options[{k}].id", "questionId": question_id,
                               "message": f"第 {k + 1} 个选项的 id {oid} 不是本题已有的选项（新增选项不要带 id）"})
                continue
            kept.add(oid)
            new_options.append({"id": oid, "text": o["text"].strip()})
        if errors:
            raise ValidationFailed(errors, "题目设置不合法")
        question["options"] = new_options
    question["validation"] = _normalize_validation(validation)
    if logic is not None:
        question["logic"] = {"rules": logic.get("rules", []),
                             "defaultNext": logic.get("defaultNext"),
                             **{k: v for k, v in logic.items() if k not in ("rules", "defaultNext")}}

    if "source" in questions[i]:
        # 第二阶段：来自题目库的题只能改是否必答和跳转规则（没有 source 的题不经过这里）
        _check_library_content_unchanged(questions[i], question, i)
        question["source"] = questions[i]["source"]

    questions[i] = question
    return _save(db, owner_id, survey, questions)


# ---------- 删除 ----------
def delete_question(db: Database, owner_id: ObjectId, survey_id: str, question_id: str,
                    expected_updated_at: datetime | None = None) -> dict:
    survey = _load_editable(db, owner_id, survey_id, expected_updated_at)
    i = _find_index(survey, question_id)
    refs = find_references(survey["questions"], question_id)
    if refs:
        errors = [{"field": "id", "questionId": question_id, "message": f"{r}跳转到这道题"} for r in refs]
        raise Conflict("QUESTION_REFERENCED", f"{refs[0]}跳转到这道题，请先修改该规则", errors)
    questions = survey["questions"][:i] + survey["questions"][i + 1:]
    return _save(db, owner_id, survey, questions)


# ---------- 调整顺序 ----------
def reorder_questions(db: Database, owner_id: ObjectId, survey_id: str, question_ids: list[str],
                      expected_updated_at: datetime | None = None) -> dict:
    survey = _load_editable(db, owner_id, survey_id, expected_updated_at)
    by_id = {q["id"]: q for q in survey["questions"]}
    if len(question_ids) != len(by_id) or set(question_ids) != set(by_id):
        raise ValidationFailed([{"field": "questionIds",
                                 "message": "必须恰好包含问卷的全部题目 id，且不能重复"}])
    return _save(db, owner_id, survey, [by_id[qid] for qid in question_ids])


# ---------- 第二阶段：使用题目库中的题（设计文档 10.5） ----------
def _content_without_required(q: dict) -> dict:
    content = {k: q.get(k) for k in ("type", "title", "options")}
    content["validation"] = {k: v for k, v in (q.get("validation") or {}).items() if k != "required"}
    return content


def _check_library_content_unchanged(old: dict, new: dict, index: int) -> None:
    if _content_without_required(old) != _content_without_required(new):
        raise ValidationFailed([{
            "questionId": old["id"], "field": "source",
            "message": f"第 {index + 1} 题来自已保存的题目，题目内容和校验不能在问卷里修改，只能修改是否必答和跳转规则；"
                       "要修改内容，请在“我的题目”中创建新版本后换版本"}], "题目设置不合法")


def _check_not_in_survey(questions: list[dict], root_id: ObjectId, skip_index: int | None = None) -> None:
    for k, q in enumerate(questions):
        if k != skip_index and (q.get("source") or {}).get("rootId") == root_id:
            raise Conflict("QUESTION_ALREADY_IN_SURVEY",
                           f"这道题已经在问卷中（第 {k + 1} 题），同一道题在一份问卷中只能出现一次")


def _check_option_ids_free(version: dict, used: set[str]) -> None:
    clash = [o["id"] for o in version.get("options") or [] if o["id"] in used]
    if clash:
        raise Conflict("OPTION_ID_CONFLICT",
                       f"这道题的选项 id {', '.join(clash)} 与问卷中其他题目的 id 重复，无法添加")


def _library_question(qid: str, version: dict, required: bool, logic: dict | None) -> dict:
    """由加锁后的版本生成问卷中的题目：内容是副本，required 和 logic 由问卷决定。"""
    content = copy.deepcopy(library.snapshot(version))
    question = {"id": qid, **content, "validation": {**content["validation"], "required": required}}
    if logic is not None:
        question["logic"] = logic
    question["source"] = library.source_of(version)
    return question


def add_from_library(db: Database, owner_id: ObjectId, survey_id: str, *, question_id: str,
                     required: bool, position: int | None,
                     expected_updated_at: datetime | None = None) -> dict:
    """把一个可访问的题目版本复制进草稿问卷（跳转规则添加后再设，与第一阶段添加题目一致）。"""
    survey = _load_editable(db, owner_id, survey_id, expected_updated_at)
    questions = list(survey["questions"])
    if position is not None and not 1 <= position <= len(questions) + 1:
        raise ValidationFailed([{"field": "position",
                                 "message": f"position 应为 1~{len(questions) + 1}"}])
    if len(questions) >= MAX_QUESTIONS:
        # 提前检查，避免为一次注定失败的添加给版本加锁
        raise ValidationFailed([{"questionId": None, "field": "questions",
                                 "message": f"每份问卷最多 {MAX_QUESTIONS} 道题"}], "题目设置不合法")
    version = library.get_accessible(db, owner_id, question_id)
    _check_not_in_survey(questions, version["rootId"])

    version = library.lock_for_use(db, owner_id, question_id)
    used = _used_ids(questions)
    _check_option_ids_free(version, used)
    used.update(o["id"] for o in version.get("options") or [])
    question = _library_question(new_id("q_", used), version, required, None)

    index = len(questions) if position is None else position - 1
    questions.insert(index, question)
    return _save(db, owner_id, survey, questions)


def switch_version(db: Database, owner_id: ObjectId, survey_id: str, question_id: str, *,
                   version_id: str, expected_updated_at: datetime | None = None) -> dict:
    """草稿中来自题目库的题换成同一道题的另一个版本：保留题目 id、是否必答、跳转规则（10.5）。
    规则引用的选项在新版本中不存在时，整体检查会拒绝并指出是哪条规则。"""
    survey = _load_editable(db, owner_id, survey_id, expected_updated_at)
    questions = list(survey["questions"])
    i = _find_index(survey, question_id)
    old = questions[i]
    if "source" not in old:
        raise Conflict("NOT_FROM_LIBRARY", "这道题是在问卷中直接创建的，没有来源版本，不能换版本")
    target = library.get_accessible(db, owner_id, version_id)
    if target["rootId"] != old["source"]["rootId"]:
        raise ValidationFailed([{"questionId": question_id, "field": "questionId",
                                 "message": "只能换成同一道题的其他版本；要用另一道题，请删除后重新添加"}])
    if target["_id"] == old["source"]["questionId"]:
        return survey  # 已经是这个版本

    version = library.lock_for_use(db, owner_id, version_id)
    others = questions[:i] + questions[i + 1:]
    _check_option_ids_free(version, _used_ids(others) | {question_id})
    questions[i] = _library_question(question_id, version, old["validation"].get("required", False),
                                     old.get("logic"))
    return _save(db, owner_id, survey, questions)


def save_to_library(db: Database, owner_id: ObjectId, survey_id: str, question_id: str
                    ) -> tuple[dict, dict]:
    """把问卷中直接建的题存进题目库（10.5）：生成新题 v1（选项 id 沿用），并给原问卷的题补上 source。

    不改题目内容，因此任何状态的问卷都可以（已发布、已关闭的问卷只是补充来源信息，答卷不变）。
    先创建 v1，再用条件更新给问卷的题补 source；后者失败（已被存过、问卷期间被修改）时撤销 v1。
    返回 (更新后的问卷, 新版本)。
    """
    survey = get_owned(db, owner_id, survey_id)
    i = _find_index(survey, question_id)
    if "source" in survey["questions"][i]:
        raise _already_in_library()

    version = library.create_from_survey_question(db, owner_id, survey["questions"][i])
    now = max(now_utc(), survey["updatedAt"] + timedelta(milliseconds=1))
    updated = surveys_repo.set_question_source(db, survey["_id"], owner_id, question_id,
                                               library.source_of(version), survey["updatedAt"], now)
    if updated is None:
        library.discard(db, version["_id"])
        current = surveys_repo.find_owned(db, survey["_id"], owner_id)
        q = next((q for q in (current or {}).get("questions", []) if q["id"] == question_id), None)
        if q is None:
            raise NotFound("QUESTION_NOT_FOUND", "题目不存在")
        if "source" in q:
            raise _already_in_library()
        raise _edit_conflict()
    return updated, version


def _already_in_library() -> Conflict:
    return Conflict("ALREADY_IN_LIBRARY", "这道题来自已保存的题目（或已存入“我的题目”），不能重复存入")
