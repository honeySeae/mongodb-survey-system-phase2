"""生成示例数据：一份已发布的示例问卷“大学生饮食习惯调查”和 12 位填写人的 13 份答卷。

用法（在项目根目录，先启动 MongoDB）：
    python -m scripts.seed_demo                         # 已存在时不重复生成，直接输出链接
    python -m scripts.seed_demo --reset                 # 删除示例问卷及其答卷后重新生成
    python -m scripts.seed_demo --owner-password XXX    # 指定创建者密码（部署到服务器时请使用）

第二阶段：本命令同时生成第二阶段的示例数据（课程评价：题目复用、版本、共享、题库、跨问卷统计），
见 scripts/seed_phase2.py；--reset 也会重新生成第二阶段的示例数据。本文件中第一阶段的示例数据不变。

直接调用服务层（与网页提交走完全相同的校验、跳转计算和提交策略），不需要先启动服务。
数据写入 .env 中配置的数据库；问卷链接的前缀来自 PUBLIC_BASE_URL。

示例问卷的链接代码固定为 Food26（访问链接 <PUBLIC_BASE_URL>/survey/Food26），重新生成也不变，
README 和报告中可以直接写这个链接。已存在的旧示例问卷（随机链接）会被改为 Food26，答卷保留。
Food26 已被其他问卷占用时报错停止，不会覆盖那份问卷。

问卷设计（2026-10-19 开发者确认，见 AI_LOG 第 27 条）：12 道题覆盖四种题型；
单选跳转（第 1 题“否”→ 结束问卷；第 4 题“基本不吃”→ 第 6 题；第 5 题 → 第 7 题）、
多选跳转（第 7 题选了“外卖”→ 第 8 题，否则 → 第 10 题）、数字跳转（第 8 题 ≥ 7 → 第 9 题）；
必答、多选最多/至少到最多/必须选 2 项、文本字数、数字范围与整数（年龄 0–120 的整数）。
实名、latest 策略、不限截止时间。
"""
import argparse

from bson import ObjectId
from pymongo.database import Database

from app.config import get_settings
from app.db import RESPONSES, SURVEYS, get_db
from app.db_schema import ensure_schema
from app.errors import Conflict
from app.logic.survey_check import check_survey
from app.repositories import users as users_repo
from app.services import auth as auth_service
from app.services import fill as fill_service
from app.services import questions as question_service
from app.services import surveys as survey_service

DEMO_TITLE = "大学生饮食习惯调查"
DEMO_SHORT_CODE = "Food26"   # 固定的链接代码（2026-10-22 开发者要求，见 AI_LOG 第 32 条）
DEMO_DESCRIPTION = "了解在校大学生的一日三餐、外卖和饮食花费情况，结果仅用于课程项目演示。大约需要 2 分钟。"
OWNER = "demo_owner"
DEFAULT_PASSWORD = "demo123456"
RESPONDENTS = [f"demo_s{i:02d}" for i in range(1, 13)]

# 12 道题：(题型, 题目, 选项, 校验)
QUESTIONS = [
    ("single_choice", "你目前是在校大学生（含研究生）吗？", ["是", "否"], {"required": True}),
    ("number", "你的年龄（周岁）？", None, {"required": True, "min": 0, "max": 120, "integerOnly": True}),
    ("single_choice", "你的年级？", ["大一", "大二", "大三", "大四", "研究生"], {"required": True}),
    ("single_choice", "你吃早餐的频率？", ["每天都吃", "每周 3–6 次", "每周 1–2 次", "基本不吃"], {"required": True}),
    ("single_choice", "你的早餐通常在哪里解决？", ["食堂", "便利店", "宿舍自备", "路边摊"], {"required": True}),
    ("multiple_choice", "你不吃早餐的主要原因？", ["起不来", "没胃口", "节省时间", "省钱", "控制体重"],
     {"required": True, "maxSelect": 2}),
    ("multiple_choice", "你平时主要在哪些地方就餐？", ["学校食堂", "外卖", "校外餐馆", "自己做饭"],
     {"required": True, "minSelect": 1, "maxSelect": 3}),
    ("number", "你平均每周点几次外卖？", None, {"required": True, "min": 0, "max": 50, "integerOnly": True}),
    ("text", "你经常点外卖的主要原因是什么？", None, {"required": False, "minLength": 5, "maxLength": 200}),
    ("number", "你每月的餐饮支出大约是多少元？", None, {"required": True, "min": 0, "max": 10000, "integerOnly": True}),
    ("multiple_choice", "选择就餐时，你最看重哪两点？", ["口味", "价格", "营养健康", "方便快捷", "卫生"],
     {"required": True, "minSelect": 2, "maxSelect": 2}),
    ("text", "你对学校食堂有什么建议？", None, {"required": False, "maxLength": 300}),
]

# 示例答卷：题号（从 1 开始）-> 答案；选择题写选项文字，生成时换成选项 id。各人作答路径不同。
ANSWERS = {
    "demo_s01": {1: "是", 2: 19, 3: "大一", 4: "每天都吃", 5: "食堂", 7: ["学校食堂"], 10: 800,
                 11: ["价格", "营养健康"], 12: "希望多一些清淡的菜"},
    "demo_s02": {1: "是", 2: 21, 3: "大三", 4: "基本不吃", 6: ["起不来", "节省时间"], 7: ["学校食堂", "外卖"], 8: 9,
                 9: "晚上自习到很晚，食堂已经关门了", 10: 1600, 11: ["口味", "方便快捷"]},
    "demo_s03": {1: "否"},                                              # 不是在校大学生 → 结束问卷
    "demo_s04": {1: "是", 2: 22, 3: "大四", 4: "每周 3–6 次", 5: "便利店", 7: ["外卖", "校外餐馆"], 8: 3,
                 10: 1200, 11: ["口味", "卫生"]},
    "demo_s05": {1: "是", 2: 25, 3: "研究生", 4: "每天都吃", 5: "宿舍自备", 7: ["学校食堂", "自己做饭"], 10: 900,
                 11: ["营养健康", "卫生"], 12: "研究生公寓附近能加一个食堂窗口吗"},
    "demo_s06": {1: "是", 2: 18, 3: "大一", 4: "每周 1–2 次", 5: "食堂", 7: ["学校食堂", "外卖"], 8: 2,
                 10: 700, 11: ["价格", "方便快捷"]},
    "demo_s07": {1: "是", 2: 20, 3: "大二", 4: "基本不吃", 6: ["没胃口"], 7: ["外卖"], 8: 14,
                 10: 2000, 11: ["口味", "方便快捷"]},                  # 每周 14 次进入第 9 题，但选填未答
    "demo_s08": {1: "否"},
    "demo_s09": {1: "是", 2: 23, 3: "大四", 4: "每天都吃", 5: "路边摊", 7: ["学校食堂", "外卖", "校外餐馆"], 8: 7,
                 9: "校外的选择多，味道也更好", 10: 1800, 11: ["口味", "价格"]},
    "demo_s10": {1: "是", 2: 17, 3: "大一", 4: "每天都吃", 5: "食堂", 7: ["学校食堂"], 10: 650,
                 11: ["价格", "卫生"], 12: "饭卡充值能不能支持手机"},
    "demo_s11": {1: "是", 2: 29, 3: "研究生", 4: "每周 3–6 次", 5: "便利店", 7: ["学校食堂", "自己做饭"], 10: 1000,
                 11: ["营养健康", "价格"]},
    "demo_s12": {1: "是", 2: 20, 3: "大二", 4: "基本不吃", 6: ["省钱", "控制体重"], 7: ["学校食堂"], 10: 500,
                 11: ["价格", "营养健康"], 12: "希望食堂能标注菜品的热量"},
}
# demo_s02 再提交一次（latest 策略：以最后一次为准）：外卖改为每周 4 次（不再进入第 9 题），并补充建议
RESUBMIT = ("demo_s02", {1: "是", 2: 21, 3: "大三", 4: "基本不吃", 6: ["起不来", "节省时间"], 7: ["学校食堂", "外卖"],
                         8: 4, 10: 1400, 11: ["口味", "方便快捷"], 12: "早餐窗口能开到九点就好了"})


def _ensure_user(db: Database, username: str, password: str) -> tuple[ObjectId, bool]:
    """返回 (用户 id, 是否新建)。账号已存在时沿用（不修改其密码）。"""
    existing = users_repo.find_by_username(db, username)
    if existing:
        return existing["_id"], False
    try:
        return auth_service.register(db, username, password)["_id"], True
    except Conflict:  # 并发运行时可能刚被创建
        return users_repo.find_by_username(db, username)["_id"], False


class SeedError(Exception):
    """无法生成示例数据（如固定链接代码已被其他问卷占用）。"""


def _ensure_code_available(db: Database, except_id: ObjectId | None = None) -> None:
    other = db[SURVEYS].find_one({"shortCode": DEMO_SHORT_CODE, "_id": {"$ne": except_id}})
    if other:
        raise SeedError(f"链接代码 {DEMO_SHORT_CODE} 已被另一份问卷《{other['title']}》占用，"
                        f"为避免覆盖，未做任何修改")


def _find_demo_survey(db: Database, owner_id: ObjectId) -> dict | None:
    return db[SURVEYS].find_one({"ownerId": owner_id, "title": DEMO_TITLE})


def _build_survey(db: Database, owner_id: ObjectId) -> dict:
    survey = survey_service.create_survey(
        db, owner_id, title=DEMO_TITLE, description=DEMO_DESCRIPTION,
        allow_anonymous=False, submission_policy="latest", deadline=None, short_code=DEMO_SHORT_CODE)
    sid = str(survey["_id"])
    for qtype, title, options, validation in QUESTIONS:
        survey = question_service.add_question(
            db, owner_id, sid, qtype=qtype, title=title,
            options=[{"text": t} for t in options] if options else None,
            validation=validation, position=None, logic_given=False)

    qs = survey["questions"]
    qid = {n: q["id"] for n, q in enumerate(qs, start=1)}
    opt = {(n, o["text"]): o["id"] for n, q in enumerate(qs, start=1) for o in q.get("options", [])}

    def set_logic(n: int, rules: list[tuple], default: int | str | None = None):
        q = qs[n - 1]
        logic = {
            "rules": [{"when": {"op": op, "value": value}, "goto": qid.get(goto, goto)} for op, value, goto in rules],
            "defaultNext": qid.get(default, default),
        }
        return question_service.update_question(
            db, owner_id, sid, q["id"], qtype=q["type"], title=q["title"], options=q.get("options"),
            validation=q["validation"], logic=logic)

    set_logic(1, [("eq", opt[(1, "否")], "END")])                     # 单选跳到结束问卷
    set_logic(4, [("eq", opt[(4, "基本不吃")], 6)])                   # 单选往后跳
    set_logic(5, [], default=7)                                       # 吃早餐的人跳过第 6 题
    set_logic(7, [("contains", opt[(7, "外卖")], 8)], default=10)     # 多选跳转
    survey = set_logic(8, [("gte", 7, 9)], default=10)                # 数字跳转

    check = check_survey(survey["questions"])
    assert check.ok and not check.warnings, (check.errors, check.warnings)
    return survey_service.publish_survey(db, owner_id, sid)


def _to_items(survey: dict, answers: dict[int, object]) -> list[dict]:
    qs = survey["questions"]
    items = []
    for n, value in answers.items():
        q = qs[n - 1]
        texts = {o["text"]: o["id"] for o in q.get("options", [])}
        if q["type"] == "single_choice":
            value = texts[value]
        elif q["type"] == "multiple_choice":
            value = [texts[v] for v in value]
        items.append({"questionId": q["id"], "value": value})
    return items


def seed(db: Database, *, reset: bool = False, owner_password: str = DEFAULT_PASSWORD,
         respondent_password: str = DEFAULT_PASSWORD) -> dict:
    """生成示例数据（幂等），返回摘要。"""
    ensure_schema(db)
    owner_id, owner_created = _ensure_user(db, OWNER, owner_password)
    existing = _find_demo_survey(db, owner_id)
    if existing and reset:
        db[RESPONSES].delete_many({"surveyId": existing["_id"]})
        db[SURVEYS].delete_one({"_id": existing["_id"]})
        existing = None

    old_code = None
    if existing and existing["shortCode"] != DEMO_SHORT_CODE:
        # 旧版本脚本生成的示例问卷使用随机链接：改为固定值，答卷保留
        _ensure_code_available(db, except_id=existing["_id"])
        old_code = existing["shortCode"]
        db[SURVEYS].update_one({"_id": existing["_id"]}, {"$set": {"shortCode": DEMO_SHORT_CODE}})
        existing = db[SURVEYS].find_one({"_id": existing["_id"]})

    created = existing is None
    if created:
        _ensure_code_available(db)
        survey = _build_survey(db, owner_id)
        user_ids = {name: _ensure_user(db, name, respondent_password)[0] for name in RESPONDENTS}
        for name in RESPONDENTS:
            fill_service.submit(db, survey["shortCode"], user_ids[name], _to_items(survey, ANSWERS[name]))
        name, answers = RESUBMIT
        fill_service.submit(db, survey["shortCode"], user_ids[name], _to_items(survey, answers))
    else:
        survey = existing

    return {
        "created": created,
        "owner_created": owner_created,
        "old_short_code": old_code,          # 本次由随机链接改为固定链接时，原来的链接代码
        "survey_id": str(survey["_id"]),
        "short_code": survey["shortCode"],
        "url": f"{get_settings().public_base_url}/survey/{survey['shortCode']}",
        "responses": db[RESPONSES].count_documents({"surveyId": survey["_id"]}),
        "respondents": len(db[RESPONSES].distinct("respondentId", {"surveyId": survey["_id"]})),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="生成示例问卷“大学生饮食习惯调查”及示例答卷")
    parser.add_argument("--reset", action="store_true", help="删除示例问卷及其答卷后重新生成")
    parser.add_argument("--owner-password", default=DEFAULT_PASSWORD,
                        help=f"创建者 {OWNER} 的密码（仅在账号不存在时使用；部署到服务器时请指定）")
    args = parser.parse_args()

    try:
        result = seed(get_db(), reset=args.reset, owner_password=args.owner_password)
    except SeedError as e:
        raise SystemExit(f"无法生成示例问卷：{e}")
    print("已生成示例问卷" if result["created"] else "示例问卷已存在，未重复生成（使用 --reset 可重新生成）")
    if result["old_short_code"]:
        print(f"  已把示例问卷的链接由 {result['old_short_code']} 改为固定的 {DEMO_SHORT_CODE}（答卷保留）")
    print(f"  问卷：{DEMO_TITLE}（已发布，实名，可以重填、以最后一次为准，不限截止时间）")
    print(f"  链接：{result['url']}")
    print(f"  答卷：{result['responses']} 份，填写人 {result['respondents']} 位")
    owner_pw = f" / {args.owner_password}" if result["owner_created"] else "（账号已存在，沿用原密码）"
    print(f"  创建者账号：{OWNER}{owner_pw}，登录后在“我的问卷”中查看统计")
    print(f"  填写人账号：{RESPONDENTS[0]} ~ {RESPONDENTS[-1]}，密码 {DEFAULT_PASSWORD}（新建时）")

    # 第二阶段示例数据（放在函数内导入：seed_phase2 复用了本文件的账号工具）
    from scripts import seed_phase2
    print()
    seed_phase2.print_summary(seed_phase2.seed(get_db(), reset=args.reset))


if __name__ == "__main__":
    main()
