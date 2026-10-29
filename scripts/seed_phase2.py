"""第二阶段示例数据：一门课连续三个学期的课程评价，演示题目复用、版本、共享、题库和跨问卷统计。

用法（在项目根目录，先启动 MongoDB）：
    python -m scripts.seed_demo            # 同时生成第一阶段和第二阶段的示例数据
    python -m scripts.seed_phase2          # 只生成第二阶段的示例数据
    python -m scripts.seed_phase2 --reset  # 删除第二阶段示例账号的问卷、答卷、题目、题库后重新生成

与第一阶段示例脚本一样直接调用服务层（与网页操作走相同的校验、版本、共享和提交规则）。
已存在时不重复生成。只读写两个示例账号（demo_teacher、demo_colleague）的数据，填写人沿用 demo_s01 ~ demo_s12。

故事（每一步都对应第二阶段的一项需求）：
1. 老师 demo_teacher 在“我的题目”中建了“总体满意度”“每周课后学习时间”“最喜欢的教学环节”三道题，
   2025 秋的课程评价直接从中选题；“对课程的建议”是在问卷里直接建的，发布后“存入我的题目”。
2. 2026 春修改了“总体满意度”：删掉“很不满意”，“一般”改为“说不上好坏”（v2）；“最喜欢的教学环节”加了“小组讨论”（v2）。
   2026 春的问卷用 v2；去年的问卷仍是原来的内容（需求三）。
3. 之后又试改了一版（v3：改了题目、加了一个选项），觉得不好，恢复 v2 的内容成为 v4（需求四：恢复旧版本）。
   2026 秋的问卷用 v4，并设置了跳转规则（选“不满意”直接跳到建议）。
4. 三份问卷提交策略不同（只能填一次 / 以最后一次为准 / 每次都算），各有几份答卷——跨问卷统计（需求八）。
5. 老师把“总体满意度”共享给同事 demo_colleague，把“对课程的建议”设为公开（需求二）；
   建了题库“课程评价常用题”并共享给同事（需求七）。题库中“总体满意度”“最喜欢的教学环节”仍是 v2，
   会提示“有新版本可换”；同事共享过来的“你的专业”后来被同事取消共享，在题库中显示不可用及原因。
6. 同事基于“总体满意度”创建了自己的版本（属于同事、不共享），并用它和题库中的题做了助教课评价——
   老师查看“被哪些问卷使用”时，别人的问卷只显示数量（需求六）。
"""
import argparse

from bson import ObjectId
from pymongo.database import Database

from app.config import get_settings
from app.db import QUESTION_BANKS, QUESTIONS, RESPONSES, SURVEYS, get_db
from app.db_schema import ensure_schema
from app.services import banks as bank_service
from app.services import fill as fill_service
from app.services import question_library as library
from app.services import questions as question_service
from app.services import surveys as survey_service
from scripts.seed_demo import DEFAULT_PASSWORD, RESPONDENTS, _ensure_user

TEACHER = "demo_teacher"
COLLEAGUE = "demo_colleague"
COURSE = "《数据库原理》课程评价"
SURVEYS_INFO = {   # 键 -> (标题, 链接代码, 提交策略)
    "2025F": (f"{COURSE}（2025 秋）", "Db25Fa", "once"),
    "2026S": (f"{COURSE}（2026 春）", "Db26Sp", "latest"),
    "2026F": (f"{COURSE}（2026 秋）", "Db26Fa", "all"),
}
TA_SURVEY = ("《数据库原理》助教课评价", "DbTa26", "once")
BANK_NAME = "课程评价常用题"

SATISFACTION_V1 = ["非常满意", "满意", "一般", "不满意", "很不满意"]

# 答卷：(填写人, {题: 答案})；选择题写选项文字。题：sat 满意度、hours 学习时间、parts 教学环节、advice 建议
ANSWERS = {
    "2025F": [
        ("demo_s01", {"sat": "满意", "hours": 4, "parts": ["课堂讲授", "实验课"], "advice": "实验课时间可以再长一点"}),
        ("demo_s02", {"sat": "一般", "hours": 2, "parts": ["课堂讲授"]}),
        ("demo_s03", {"sat": "很不满意", "hours": 0, "parts": ["课后作业"], "advice": "进度太快，跟不上"}),
        ("demo_s04", {"sat": "非常满意", "hours": 6, "parts": ["实验课", "课后作业"]}),
        ("demo_s05", {"sat": "很不满意", "hours": 1, "parts": ["课堂讲授"], "advice": "希望多讲例题"}),
        ("demo_s06", {"sat": "满意", "hours": 3, "parts": ["实验课"]}),
    ],
    "2026S": [
        ("demo_s01", {"sat": "满意", "hours": 5, "parts": ["实验课"], "advice": "MongoDB 的部分很有意思"}),
        ("demo_s07", {"sat": "说不上好坏", "hours": 2, "parts": ["课堂讲授", "课后作业"]}),
        ("demo_s08", {"sat": "非常满意", "hours": 8, "parts": ["实验课", "课后作业"]}),
        ("demo_s09", {"sat": "不满意", "hours": 1, "parts": ["课堂讲授"], "advice": "作业批改反馈太慢"}),
        ("demo_s10", {"sat": "满意", "hours": 4, "parts": ["实验课"]}),
        # latest：demo_s07 改了答案，以最后一次为准
        ("demo_s07", {"sat": "满意", "hours": 3, "parts": ["课堂讲授", "实验课"], "advice": "期中后节奏好多了"}),
    ],
    "2026F": [
        ("demo_s02", {"sat": "非常满意", "hours": 6, "parts": ["小组讨论", "实验课"], "advice": "小组讨论很有收获"}),
        ("demo_s03", {"sat": "满意", "hours": 3, "parts": ["小组讨论"]}),
        ("demo_s11", {"sat": "不满意", "advice": "讨论时间太少"}),          # 跳转：不满意 → 直接到建议
        ("demo_s12", {"sat": "满意", "hours": 5, "parts": ["课堂讲授", "小组讨论"]}),
        ("demo_s04", {"sat": "说不上好坏", "hours": 2, "parts": ["课后作业"]}),
        # all：demo_s12 期末又填了一次，两次都算
        ("demo_s12", {"sat": "非常满意", "hours": 7, "parts": ["小组讨论", "实验课"], "advice": "期末复习课很有用"}),
    ],
}
TA_ANSWERS = [
    ("demo_s05", {"sat": "满意", "hours": 2}),
    ("demo_s06", {"sat": "还行", "hours": 1}),
    ("demo_s09", {"sat": "非常满意", "hours": 4}),
]


def _sid(doc: dict) -> str:
    return str(doc["_id"])


def _items(survey: dict, keys: dict[str, str], answers: dict[str, object]) -> list[dict]:
    """{题: 答案} -> 提交格式；keys 为 题 -> 问卷中的题目 id。"""
    by_id = {q["id"]: q for q in survey["questions"]}
    items = []
    for key, value in answers.items():
        q = by_id[keys[key]]
        texts = {o["text"]: o["id"] for o in q.get("options") or []}
        if q["type"] == "single_choice":
            value = texts[value]
        elif q["type"] == "multiple_choice":
            value = [texts[v] for v in value]
        items.append({"questionId": q["id"], "value": value})
    return items


def _options(doc: dict, renames: dict[str, str] | None = None, drop: tuple = (), add: tuple = ()) -> list[dict]:
    """基于一个版本的选项构造新版本的选项：保留的带原 id（改文字也保留 id），删除 drop，追加 add。"""
    renames = renames or {}
    kept = [{"id": o["id"], "text": renames.get(o["text"], o["text"])} for o in doc["options"] if o["text"] not in drop]
    return kept + [{"text": t} for t in add]


def _new_survey(db: Database, owner_id: ObjectId, key_info: tuple, library_items: list[tuple]) -> tuple[dict, dict]:
    """建问卷并从“我的题目”添加题目，返回 (问卷, 题 -> 问卷中的题目 id)。library_items: [(题, 版本)]。"""
    title, code, policy = key_info
    survey = survey_service.create_survey(db, owner_id, title=title, description="课程结束后填写，帮助改进教学。大约需要 1 分钟。",
                                          allow_anonymous=False, submission_policy=policy, deadline=None,
                                          short_code=code)
    keys = {}
    for key, version in library_items:
        survey = question_service.add_from_library(db, owner_id, _sid(survey), question_id=_sid(version),
                                                   required=key != "advice", position=None)
        keys[key] = survey["questions"][-1]["id"]
    return survey, keys


def _publish_and_fill(db: Database, owner_id: ObjectId, survey: dict, keys: dict, answers: list, users: dict) -> dict:
    survey = survey_service.publish_survey(db, owner_id, _sid(survey))
    for name, values in answers:
        fill_service.submit(db, survey["shortCode"], users[name], _items(survey, keys, values))
    return survey


def _build(db: Database) -> dict:
    users = {name: _ensure_user(db, name, DEFAULT_PASSWORD)[0] for name in RESPONDENTS}
    teacher = _ensure_user(db, TEACHER, DEFAULT_PASSWORD)[0]
    colleague = _ensure_user(db, COLLEAGUE, DEFAULT_PASSWORD)[0]

    # ---------- 1. 我的题目 + 2025 秋 ----------
    sat1 = library.create_question(db, teacher, qtype="single_choice", title="你对这门课的总体满意度",
                                   options=[{"text": t} for t in SATISFACTION_V1], validation={})
    hours = library.create_question(db, teacher, qtype="number", title="你每周课后学习这门课大约多少小时",
                                    options=None, validation={"min": 0, "max": 40, "integerOnly": True})
    parts1 = library.create_question(db, teacher, qtype="multiple_choice", title="你最喜欢哪些教学环节",
                                     options=[{"text": t} for t in ("课堂讲授", "实验课", "课后作业")],
                                     validation={"minSelect": 1, "maxSelect": 2})
    s25, k25 = _new_survey(db, teacher, SURVEYS_INFO["2025F"], [("sat", sat1), ("hours", hours), ("parts", parts1)])
    s25 = question_service.add_question(db, teacher, _sid(s25), qtype="text", title="你对这门课有什么建议",
                                        options=None, validation={"required": False, "maxLength": 300},
                                        position=None, logic_given=False)
    k25["advice"] = s25["questions"][-1]["id"]
    s25 = _publish_and_fill(db, teacher, s25, k25, ANSWERS["2025F"], users)
    # 发布后把问卷中直接建的“建议”存入我的题目（只补来源，不改内容）
    s25, advice = question_service.save_to_library(db, teacher, _sid(s25), k25["advice"])

    # ---------- 2. 修改题目生成新版本 + 2026 春 ----------
    sat2 = library.derive_version(db, teacher, _sid(sat1), qtype="single_choice", title=sat1["title"],
                                  options=_options(sat1, renames={"一般": "说不上好坏"}, drop=("很不满意",)),
                                  validation={})
    parts2 = library.derive_version(db, teacher, _sid(parts1), qtype="multiple_choice", title=parts1["title"],
                                    options=_options(parts1, add=("小组讨论",)), validation={"minSelect": 1, "maxSelect": 2})
    s26s, k26s = _new_survey(db, teacher, SURVEYS_INFO["2026S"],
                             [("sat", sat2), ("hours", hours), ("parts", parts1), ("advice", advice)])
    _publish_and_fill(db, teacher, s26s, k26s, ANSWERS["2026S"], users)

    # ---------- 3. 试改 v3，恢复 v2 成为 v4 + 2026 秋（含跳转） ----------
    sat3 = library.derive_version(db, teacher, _sid(sat2), qtype="single_choice", title="请为这门课打分",
                                  options=_options(sat2, add=("没怎么上课",)), validation={})
    sat4 = library.restore_version(db, teacher, _sid(sat2), parent_id=_sid(sat3))
    s26f, k26f = _new_survey(db, teacher, SURVEYS_INFO["2026F"],
                             [("sat", sat4), ("hours", hours), ("parts", parts2), ("advice", advice)])
    q_sat = next(q for q in s26f["questions"] if q["id"] == k26f["sat"])
    unhappy = next(o["id"] for o in q_sat["options"] if o["text"] == "不满意")
    s26f = question_service.update_question(
        db, teacher, _sid(s26f), q_sat["id"], qtype=q_sat["type"], title=q_sat["title"], options=q_sat["options"],
        validation=q_sat["validation"], logic={"rules": [{"when": {"op": "eq", "value": unhappy}, "goto": k26f["advice"]}],
                                               "defaultNext": None})
    _publish_and_fill(db, teacher, s26f, k26f, ANSWERS["2026F"], users)

    # ---------- 5. 共享、题库 ----------
    major = library.create_question(db, colleague, qtype="single_choice", title="你的专业",
                                    options=[{"text": t} for t in ("计算机", "软件工程", "其他")], validation={})
    library.set_sharing(db, colleague, _sid(major), public=False, usernames=[TEACHER])
    library.set_sharing(db, teacher, _sid(sat1), public=False, usernames=[COLLEAGUE])
    library.set_sharing(db, teacher, _sid(advice), public=True, usernames=[])
    bank = bank_service.create_bank(db, teacher, name=BANK_NAME,
                                    description="每学期课程评价都会用到的题；有新版本时按需更换")
    for version in (sat2, hours, parts1, advice, major):
        bank = bank_service.add_item(db, teacher, _sid(bank), _sid(version))
    bank = bank_service.set_sharing(db, teacher, _sid(bank), public=False, usernames=[COLLEAGUE])
    library.set_sharing(db, colleague, _sid(major), public=False, usernames=[])   # 同事后来取消了共享

    # ---------- 6. 同事的版本和问卷 ----------
    sat5 = library.derive_version(db, colleague, _sid(sat4), qtype="single_choice", title="你对助教课的满意度",
                                  options=_options(sat4, add=("还行",)), validation={})
    ta, kta = _new_survey(db, colleague, TA_SURVEY, [("sat", sat5), ("hours", hours)])   # hours 通过共享的题库使用
    _publish_and_fill(db, colleague, ta, kta, TA_ANSWERS, users)

    return {"satisfaction": [sat1, sat2, sat3, sat4, sat5], "hours": hours, "bank": bank}


def _existing(db: Database) -> dict | None:
    teacher = db["users"].find_one({"username": TEACHER})
    if not teacher:
        return None
    return db[SURVEYS].find_one({"ownerId": teacher["_id"], "shortCode": SURVEYS_INFO["2025F"][1]})


def _reset(db: Database) -> None:
    """只删除两个示例账号的数据（问卷、答卷、题目、题库），账号保留。"""
    owners = [u["_id"] for u in db["users"].find({"username": {"$in": [TEACHER, COLLEAGUE]}}, {"_id": 1})]
    survey_ids = [s["_id"] for s in db[SURVEYS].find({"ownerId": {"$in": owners}}, {"_id": 1})]
    db[RESPONSES].delete_many({"surveyId": {"$in": survey_ids}})
    db[SURVEYS].delete_many({"_id": {"$in": survey_ids}})
    db[QUESTIONS].delete_many({"ownerId": {"$in": owners}})
    db[QUESTION_BANKS].delete_many({"ownerId": {"$in": owners}})


def seed(db: Database, *, reset: bool = False) -> dict:
    """生成第二阶段示例数据（幂等），返回摘要。"""
    ensure_schema(db)
    if reset:
        _reset(db)
    created = _existing(db) is None
    if created:
        built = _build(db)
        satisfaction_id = _sid(built["satisfaction"][0])
        hours_id = _sid(built["hours"])
        bank_id = _sid(built["bank"])
    else:
        teacher = db["users"].find_one({"username": TEACHER})
        first = db[QUESTIONS].find_one({"ownerId": teacher["_id"], "title": "你对这门课的总体满意度", "version": 1})
        satisfaction_id = _sid(first)
        hours_id = _sid(db[QUESTIONS].find_one({"ownerId": teacher["_id"], "type": "number"}))
        bank_id = _sid(db[QUESTION_BANKS].find_one({"ownerId": teacher["_id"], "name": BANK_NAME}))
    base = get_settings().public_base_url
    return {
        "created": created,
        "satisfaction_id": satisfaction_id,
        "hours_id": hours_id,
        "bank_id": bank_id,
        "links": {
            "满意度：版本历史": f"{base}/questions/{satisfaction_id}",
            "满意度：跨问卷统计": f"{base}/questions/{satisfaction_id}/stats",
            "学习时间：跨问卷统计（数字题）": f"{base}/questions/{hours_id}/stats",
            "题库": f"{base}/banks/{bank_id}",
            **{info[0]: f"{base}/survey/{info[1]}" for info in [*SURVEYS_INFO.values(), TA_SURVEY]},
        },
    }


def print_summary(result: dict) -> None:
    print("已生成第二阶段示例数据" if result["created"] else "第二阶段示例数据已存在，未重复生成（使用 --reset 可重新生成）")
    print(f"  老师账号：{TEACHER} / {DEFAULT_PASSWORD}（主要演示账号）")
    print(f"  同事账号：{COLLEAGUE} / {DEFAULT_PASSWORD}（被共享的人）")
    for name, url in result["links"].items():
        print(f"  {name}：{url}")


def main() -> None:
    parser = argparse.ArgumentParser(description="生成第二阶段示例数据（课程评价：题目复用、版本、共享、题库、跨问卷统计）")
    parser.add_argument("--reset", action="store_true", help="删除两个示例账号的问卷、答卷、题目、题库后重新生成")
    args = parser.parse_args()
    print_summary(seed(get_db(), reset=args.reset))


if __name__ == "__main__":
    main()
