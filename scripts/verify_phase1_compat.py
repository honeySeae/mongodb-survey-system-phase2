"""第一阶段 → 第二阶段兼容性验证（一键运行，结果写成 Markdown，供报告使用）。

用法（在项目根目录，先启动 MongoDB）：
    python -m scripts.verify_phase1_compat                     # 结果写到 docs/COMPAT_VERIFICATION.md
    python -m scripts.verify_phase1_compat --keep-db           # 保留验证用的数据库，便于在网页中查看

步骤：
1. 用 git worktree 取出 phase1 标签的代码（临时目录，不影响当前工作区），在一个新的数据库（默认 survey_compat）中：
   运行第一阶段的示例数据脚本；再通过第一阶段的接口建一份匿名、“每次都算”、带跳转的问卷并填写，建一份草稿；
   最后用第一阶段的接口记录各页面数据（问卷列表、详情、统计、单题统计、答卷列表、填写者看到的问卷）作为快照。
2. 切换到当前代码（第二阶段），在同一个数据库上：初始化（创建新集合和索引）、检查旧数据未被改动、
   用相同的接口取数据与快照逐项比较，再走一遍第一阶段的各项功能，最后把旧问卷的题存入“我的题目”。
3. 每一步记录 操作 / 期望 / 实际 / 结果，写成 Markdown；有任何一步不通过时以非 0 退出码结束。

数据库连接、密钥、对外地址取自当前的 .env；验证用的数据库名必须以 _compat 结尾，开始时会先删除重建。
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = "survey_compat"
REPORT = ROOT / "docs" / "COMPAT_VERIFICATION.md"
PASSWORD = "demo123456"

# 在 phase1 代码目录中运行：生成第一阶段的数据并记录快照（只使用第一阶段已有的接口）
PHASE1_SCRIPT = r'''
import json, sys
from fastapi.testclient import TestClient
from app.main import create_app
from app.db import get_db
from scripts import seed_demo

out_path = sys.argv[1]
db = get_db()
demo = seed_demo.seed(db)

def ok(r, status=200):
    assert r.status_code == status, (r.status_code, r.text)
    return r.json()

with TestClient(create_app()) as c:
    def login(name):
        token = ok(c.post("/api/auth/login", json={"username": name, "password": "demo123456"}))["accessToken"]
        return {"Authorization": f"Bearer {token}"}
    owner = login("demo_owner")
    # 第一阶段：再建一份匿名、每次都算、带跳转的问卷（与 tests/builders.py 的水果问卷相同）
    s = ok(c.post("/api/surveys", json={"title": "旧问卷：水果偏好（匿名，每次都算）", "allowAnonymous": True,
                                         "submissionPolicy": "all"}, headers=owner), 201)
    sid = s["id"]
    def add(**q):
        return ok(c.post(f"/api/surveys/{sid}/questions", json=q, headers=owner), 201)
    add(type="single_choice", title="你喜欢吃水果吗？", options=[{"text": "喜欢"}, {"text": "不喜欢"}], validation={"required": True})
    add(type="multiple_choice", title="你喜欢哪些水果？", options=[{"text": t} for t in ("苹果", "香蕉", "榴莲")],
        validation={"required": True, "minSelect": 1, "maxSelect": 2})
    full = add(type="number", title="你每周吃几次水果？", validation={"required": True, "min": 0, "max": 50, "integerOnly": True})
    q1, q2, q3 = full["questions"]
    o = {x["text"]: x["id"] for q in (q1, q2) for x in q["options"]}
    body = {"type": q1["type"], "title": q1["title"], "options": q1["options"], "validation": q1["validation"],
            "logic": {"rules": [{"when": {"op": "eq", "value": o["不喜欢"]}, "goto": "END"}], "defaultNext": None}}
    ok(c.put(f"/api/surveys/{sid}/questions/{q1['id']}", json=body, headers=owner))
    code = ok(c.post(f"/api/surveys/{sid}/publish", headers=owner))["shortCode"]
    def submit(name, answers):
        ok(c.post(f"/api/s/{code}/responses", json={"answers": [{"questionId": k, "value": v} for k, v in answers.items()]},
                  headers=login(name)), 201)
    submit("demo_s01", {q1["id"]: o["喜欢"], q2["id"]: [o["苹果"]], q3["id"]: 5})
    submit("demo_s01", {q1["id"]: o["喜欢"], q2["id"]: [o["香蕉"], o["榴莲"]], q3["id"]: 3})
    submit("demo_s02", {q1["id"]: o["不喜欢"]})
    draft = ok(c.post("/api/surveys", json={"title": "旧草稿"}, headers=owner), 201)
    c.post(f"/api/surveys/{draft['id']}/questions", json={"type": "text", "title": "草稿中的题"}, headers=owner)

    snap = {"demo_survey_id": demo["survey_id"], "fruit_survey_id": sid, "fruit_code": code,
            "draft_survey_id": draft["id"], "list": ok(c.get("/api/surveys", headers=owner)), "surveys": {}}
    for key, survey_id in (("demo", demo["survey_id"]), ("fruit", sid), ("draft", draft["id"])):
        detail = ok(c.get(f"/api/surveys/{survey_id}", headers=owner))
        snap["surveys"][key] = {
            "detail": detail,
            "stats": ok(c.get(f"/api/surveys/{survey_id}/stats", headers=owner)),
            "question_stats": {q["id"]: ok(c.get(f"/api/surveys/{survey_id}/stats/questions/{q['id']}?limit=200", headers=owner))
                               for q in detail["questions"]},
            "responses": ok(c.get(f"/api/surveys/{survey_id}/responses?limit=100", headers=owner)),
        }
        if detail["status"] == "published":
            snap["surveys"][key]["respondent_view"] = ok(c.get(f"/api/s/{detail['shortCode']}", headers=login("demo_s05")))

db = get_db()   # 应用关闭时释放了数据库客户端，重新获取
raw = {"surveys": list(db["surveys"].find()), "responses": list(db["responses"].find()), "users": list(db["users"].find())}
from bson import json_util
snap["raw"] = json.loads(json_util.dumps(raw))
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(snap, f, ensure_ascii=False)
print("phase1 ok")
'''


class Recorder:
    def __init__(self):
        self.rows = []

    def check(self, section: str, action: str, expected: str, actual, passed: bool):
        self.rows.append((section, action, expected, str(actual), passed))
        print(("通过" if passed else "未通过") + f" | {section} | {action}", flush=True)

    @property
    def ok(self):
        return all(r[4] for r in self.rows)


def _run_phase1(env: dict, out_path: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="phase1_") as tmp:
        tree = Path(tmp) / "phase1"
        subprocess.run(["git", "worktree", "add", "--detach", str(tree), "phase1"], cwd=ROOT, check=True,
                       capture_output=True)
        try:
            result = subprocess.run([sys.executable, "-c", PHASE1_SCRIPT, str(out_path)], cwd=tree, env=env,
                                    capture_output=True, text=True, encoding="utf-8")
            if result.returncode != 0:
                raise SystemExit(f"第一阶段代码运行失败：\n{result.stdout}\n{result.stderr}")
        finally:
            subprocess.run(["git", "worktree", "remove", "--force", str(tree)], cwd=ROOT, capture_output=True)


def _without(obj, keys=("source",)):
    """去掉题目中的 source（存入“我的题目”后预期新增的字段），用于比较。"""
    if isinstance(obj, dict):
        return {k: _without(v, keys) for k, v in obj.items() if k not in keys}
    if isinstance(obj, list):
        return [_without(v, keys) for v in obj]
    return obj


def verify(db_name: str, keep_db: bool) -> Recorder:
    assert db_name.endswith("_compat"), "验证用的数据库名必须以 _compat 结尾"
    os.environ["MONGO_DB_NAME"] = db_name
    os.environ.setdefault("BCRYPT_ROUNDS", "12")
    from bson import json_util
    from fastapi.testclient import TestClient

    from app import db as app_db
    from app.config import get_settings
    from app.db_schema import INDEXES, ensure_schema
    from app.main import create_app

    settings = get_settings()
    client = app_db.get_client()
    client.drop_database(db_name)
    env = {**os.environ, "MONGO_URI": settings.mongo_uri, "MONGO_DB_NAME": db_name,
           "JWT_SECRET": settings.jwt_secret, "PUBLIC_BASE_URL": settings.public_base_url}
    rec = Recorder()

    with tempfile.TemporaryDirectory() as tmp:
        snap_path = Path(tmp) / "phase1.json"
        _run_phase1(env, snap_path)
        snap = json.loads(snap_path.read_text(encoding="utf-8"))
    db = client[db_name]
    s = "准备（第一阶段代码）"
    rec.check(s, "用 phase1 标签的代码生成示例数据并通过第一阶段接口建问卷、填写",
              "第一阶段代码正常运行", f"问卷 {len(snap['raw']['surveys'])} 份、答卷 {len(snap['raw']['responses'])} 份、"
              f"用户 {len(snap['raw']['users'])} 个", len(snap["raw"]["surveys"]) == 3)

    # ---------- 1. 切换到当前代码：初始化 ----------
    s = "1 初始化"
    ensure_schema(db)
    names = set(db.list_collection_names())
    rec.check(s, "在第一阶段的数据库上运行当前代码的初始化（应用启动时也会执行）",
              "新增 questions、questionBanks 集合和索引，不报错", sorted(names),
              {"questions", "questionBanks"} <= names)
    survey_idx = sorted(db["surveys"].index_information())
    rec.check(s, "surveys 集合的索引", "原有索引保留，新增 source 相关索引", survey_idx,
              {"shortCode_unique", "ownerId_createdAt", "questions_source_questionId",
               "questions_source_rootId_ownerId"} <= set(survey_idx))
    raw_now = json.loads(json_util.dumps({"surveys": list(db["surveys"].find()),
                                           "responses": list(db["responses"].find()), "users": list(db["users"].find())}))
    rec.check(s, "逐字段比较初始化前后的 users、surveys、responses 文档", "旧数据没有任何改动（不迁移）",
              "完全相同" if raw_now == snap["raw"] else "有差异", raw_now == snap["raw"])

    with TestClient(create_app()) as c:
        def call(method, path, token=None, **kw):
            headers = {"Authorization": f"Bearer {token}"} if token else {}
            return c.request(method, path, headers=headers, **kw)

        def login(name, password=PASSWORD):
            r = call("POST", "/api/auth/login", json={"username": name, "password": password})
            return r.json().get("accessToken") if r.status_code == 200 else None

        # ---------- 2. 注册登录 ----------
        s = "2 注册登录"
        owner = login("demo_owner")
        rec.check(s, "第一阶段注册的账号 demo_owner 用原密码登录", "登录成功（bcrypt 哈希照常验证）",
                  "成功" if owner else "失败", owner is not None)
        rec.check(s, "用错误密码登录", "401", call("POST", "/api/auth/login",
                  json={"username": "demo_owner", "password": "wrong-pass"}).status_code,
                  call("POST", "/api/auth/login", json={"username": "demo_owner", "password": "wrong-pass"}).status_code == 401)
        r = call("POST", "/api/auth/register", json={"username": "compat_new", "password": PASSWORD})
        new_user = login("compat_new")
        rec.check(s, "注册新账号 compat_new 并登录", "201，登录成功", f"{r.status_code}，{'成功' if new_user else '失败'}",
                  r.status_code == 201 and new_user is not None)

        # ---------- 3. 旧数据在第二阶段接口中的显示与第一阶段完全相同 ----------
        s = "3 旧数据显示"
        lst = call("GET", "/api/surveys", owner).json()
        rec.check(s, "我的问卷列表（GET /api/surveys）", "与第一阶段返回完全相同", "相同" if lst == snap["list"] else "不同",
                  lst == snap["list"])
        for key, label in (("demo", "示例问卷 Food26（实名、以最后一次为准）"), ("fruit", "水果问卷（匿名、每次都算）"),
                           ("draft", "旧草稿")):
            old = snap["surveys"][key]
            sid = old["detail"]["id"]
            same = {
                "详情": call("GET", f"/api/surveys/{sid}", owner).json() == old["detail"],
                "整份统计": call("GET", f"/api/surveys/{sid}/stats", owner).json() == old["stats"],
                "单题统计": all(call("GET", f"/api/surveys/{sid}/stats/questions/{qid}?limit=200", owner).json() == v
                            for qid, v in old["question_stats"].items()),
                "答卷列表": call("GET", f"/api/surveys/{sid}/responses?limit=100", owner).json() == old["responses"],
            }
            if "respondent_view" in old:
                same["填写者看到的问卷"] = call("GET", f"/api/s/{old['detail']['shortCode']}",
                                                login("demo_s05")).json() == old["respondent_view"]
            rec.check(s, f"{label}：{'、'.join(same)}", "与第一阶段返回完全相同",
                      "、".join(f"{k}{'相同' if v else '不同'}" for k, v in same.items()), all(same.values()))
        fruit_stats = call("GET", f"/api/surveys/{snap['fruit_survey_id']}/stats", owner).json()
        rec.check(s, "匿名问卷的统计", "不含填写人（没有 username、respondentId）",
                  "不含" if "username" not in json.dumps(fruit_stats) and "respondentId" not in json.dumps(fruit_stats) else "含有",
                  "username" not in json.dumps(fruit_stats) and "respondentId" not in json.dumps(fruit_stats))

        # ---------- 4. 填写、跳转、校验（旧问卷） ----------
        s = "4 填写旧问卷"
        demo = snap["surveys"]["demo"]["detail"]
        qs = demo["questions"]
        opt = {(i + 1, o["text"]): o["id"] for i, q in enumerate(qs) for o in q.get("options") or []}
        s05 = login("demo_s05")
        path = call("POST", f"/api/s/Food26/path", s05, json={"answers": [
            {"questionId": qs[0]["id"], "value": opt[(1, "是")]}, {"questionId": qs[1]["id"], "value": 20},
            {"questionId": qs[2]["id"], "value": opt[(3, "大二")]},
            {"questionId": qs[3]["id"], "value": opt[(4, "基本不吃")]}]}).json()
        rec.check(s, "路径预览：第 4 题选“基本不吃”", "下一题是第 6 题（第一阶段设置的跳转规则）",
                  f"下一题 {path.get('nextQuestionId')}", path.get("nextQuestionId") == qs[5]["id"])
        bad = call("POST", "/api/s/Food26/responses", s05, json={"answers": [
            {"questionId": qs[0]["id"], "value": opt[(1, "是")]}, {"questionId": qs[1]["id"], "value": 200}]})
        rec.check(s, "提交年龄 200（题目要求 0–120 的整数）", "422，提示超出范围", f"{bad.status_code} {bad.json().get('errors')}",
                  bad.status_code == 422)
        miss = call("POST", "/api/s/Food26/responses", s05, json={"answers": [{"questionId": qs[0]["id"], "value": opt[(1, "是")]}]})
        rec.check(s, "只答第 1 题“是”就提交（后面有必答题）", "422，提示必答题未答", miss.status_code, miss.status_code == 422)
        good = call("POST", "/api/s/Food26/responses", s05, json={"answers": [
            {"questionId": qs[0]["id"], "value": opt[(1, "否")]}, {"questionId": qs[1]["id"], "value": 30}]})
        stored = db["responses"].find_one({"surveyId": __import__("bson").ObjectId(demo["id"]), "isLatest": True,
                                           "respondentId": db["users"].find_one({"username": "demo_s05"})["_id"]})
        rec.check(s, "重填：第 1 题选“否”（跳到结束），同时多交了第 2 题的答案", "201；以最后一次为准；路径外的答案被丢弃，只保存第 1 题",
                  f"{good.status_code}；保存的题数 {len(stored['answers'])}",
                  good.status_code == 201 and len(stored["answers"]) == 1)
        stats_after = call("GET", f"/api/surveys/{demo['id']}/stats", owner).json()
        rec.check(s, "重填后的统计", "答卷数仍为 12（latest 口径）、第 1 题“否”增加 1 人",
                  f"答卷 {stats_after['totalResponses']}，否 {stats_after['questions'][0]['options'][1]['count']}",
                  stats_after["totalResponses"] == 12 and stats_after["questions"][0]["options"][1]["count"] ==
                  snap["surveys"]["demo"]["stats"]["questions"][0]["options"][1]["count"] + 1)
        fruit_code = snap["fruit_code"]
        r = call("POST", f"/api/s/{fruit_code}/responses", login("demo_s03"), json={"answers": [
            {"questionId": snap["surveys"]["fruit"]["detail"]["questions"][0]["id"],
             "value": snap["surveys"]["fruit"]["detail"]["questions"][0]["options"][1]["id"]}]})
        rec.check(s, "填写旧的匿名问卷（选“不喜欢” → 结束问卷）", "201", r.status_code, r.status_code == 201)

        # ---------- 5. 第一阶段的完整流程：建问卷、题目、跳转、发布、填写、统计 ----------
        s = "5 新建问卷（第一阶段流程）"
        new = call("POST", "/api/surveys", new_user, json={"title": "兼容性验证问卷", "submissionPolicy": "once"}).json()
        nid = new["id"]
        add = lambda q: call("POST", f"/api/surveys/{nid}/questions", new_user, json=q)
        add({"type": "single_choice", "title": "有没有宠物", "options": [{"text": "有"}, {"text": "没有"}], "validation": {"required": True}})
        add({"type": "multiple_choice", "title": "养了什么", "options": [{"text": "猫"}, {"text": "狗"}],
             "validation": {"required": True, "minSelect": 1}})
        add({"type": "text", "title": "宠物的名字", "validation": {"required": False, "maxLength": 20}})
        full = add({"type": "number", "title": "每月花费", "validation": {"required": True, "min": 0, "integerOnly": True}}).json()
        q1, q2, q3, q4 = full["questions"]
        logic = {"rules": [{"when": {"op": "eq", "value": q1["options"][1]["id"]}, "goto": q4["id"]}], "defaultNext": None}
        r = call("PUT", f"/api/surveys/{nid}/questions/{q1['id']}", new_user, json={
            "type": q1["type"], "title": q1["title"], "options": q1["options"], "validation": q1["validation"], "logic": logic})
        back = call("PUT", f"/api/surveys/{nid}/questions/{q4['id']}", new_user, json={
            "type": q4["type"], "title": q4["title"], "validation": q4["validation"],
            "logic": {"rules": [{"when": {"op": "eq", "value": 0}, "goto": q1["id"]}], "defaultNext": None}})
        rec.check(s, "建问卷、添加四种题型、设置跳转（没有宠物 → 第 4 题）；再设置一条往前跳的规则",
                  "跳转保存成功；往前跳被拒绝（422）", f"{r.status_code}；往前跳 {back.status_code}",
                  r.status_code == 200 and back.status_code == 422)
        code = call("POST", f"/api/surveys/{nid}/publish", new_user).json()["shortCode"]
        r1 = call("POST", f"/api/s/{code}/responses", owner, json={"answers": [
            {"questionId": q1["id"], "value": q1["options"][1]["id"]}, {"questionId": q2["id"], "value": [q2["options"][0]["id"]]},
            {"questionId": q4["id"], "value": 0}]})
        r2 = call("POST", f"/api/s/{code}/responses", owner, json={"answers": [{"questionId": q1["id"], "value": q1["options"][0]["id"]},
            {"questionId": q2["id"], "value": [q2["options"][0]["id"]]}, {"questionId": q4["id"], "value": 100}]})
        r3 = call("POST", f"/api/s/{code}/responses", login("demo_s01"), json={"answers": [
            {"questionId": q1["id"], "value": q1["options"][0]["id"]}, {"questionId": q2["id"], "value": ["猫"]},
            {"questionId": q4["id"], "value": 50}]})
        rec.check(s, "发布后填写：跳过第 2、3 题；同一人再交一次（once）；多选填了不存在的选项",
                  "201；409（每人只能填一次）；422（不是本题的选项）", f"{r1.status_code}；{r2.status_code}；{r3.status_code}",
                  (r1.status_code, r2.status_code, r3.status_code) == (201, 409, 422))
        st = call("GET", f"/api/surveys/{nid}/stats", new_user).json()
        rec.check(s, "统计", "答卷 1；第 1 题“没有” 1 人；第 2 题被跳过 0 份；第 4 题平均 0",
                  f"答卷 {st['totalResponses']}；没有 {st['questions'][0]['options'][1]['count']}；"
                  f"第 2 题 {st['questions'][1]['answerCount']}；平均 {st['questions'][3]['average']}",
                  st["totalResponses"] == 1 and st["questions"][0]["options"][1]["count"] == 1
                  and st["questions"][1]["answerCount"] == 0 and st["questions"][3]["average"] == 0)

        # ---------- 6. 旧问卷的题存入“我的题目” ----------
        s = "6 旧问卷的题存入我的题目"
        age = qs[1]
        before_stats = call("GET", f"/api/surveys/{demo['id']}/stats", owner).json()
        before_responses = call("GET", f"/api/surveys/{demo['id']}/responses?limit=100", owner).json()
        r = call("POST", f"/api/surveys/{demo['id']}/questions/{age['id']}/save-to-library", owner)
        saved = r.json()
        v1 = saved.get("question", {})
        rec.check(s, "已发布的旧问卷 Food26 的第 2 题（年龄）“存入我的题目”", "201；生成新题 v1（锁定），校验去掉 required",
                  f"{r.status_code}；v{v1.get('version')}，锁定 {v1.get('locked')}，校验 {v1.get('validation')}",
                  r.status_code == 201 and v1.get("version") == 1 and v1.get("locked") is True
                  and v1.get("validation") == {"min": 0, "max": 120, "integerOnly": True})
        after = call("GET", f"/api/surveys/{demo['id']}", owner).json()
        rec.check(s, "存入后的旧问卷", "只多了这道题的 source，其余（题目、选项 id、跳转规则）与原来相同",
                  f"source={after['questions'][1].get('source')}",
                  _without(after["questions"]) == _without(demo["questions"]) and "source" in after["questions"][1]
                  and all("source" not in q for i, q in enumerate(after["questions"]) if i != 1))
        same_stats = call("GET", f"/api/surveys/{demo['id']}/stats", owner).json() == before_stats
        same_resp = call("GET", f"/api/surveys/{demo['id']}/responses?limit=100", owner).json() == before_responses
        rec.check(s, "存入后旧问卷的统计、答卷列表", "与存入前完全相同（答卷不迁移、不改动）",
                  f"统计{'相同' if same_stats else '不同'}，答卷{'相同' if same_resp else '不同'}", same_stats and same_resp)
        cross = call("GET", f"/api/questions/{v1['id']}/stats", owner).json()
        single = call("GET", f"/api/surveys/{demo['id']}/stats/questions/{age['id']}", owner).json()["question"]
        rec.check(s, "这道题的跨问卷统计", "旧答卷计入：答卷数、作答人数、平均值与旧问卷的单题统计一致",
                  f"跨问卷 {cross['overall']['answerCount']} / {cross['overall']['respondentCount']} / {cross['overall']['average']}；"
                  f"单题 {single['answerCount']} / {single['respondentCount']} / {single['average']}",
                  (cross["overall"]["answerCount"], cross["overall"]["respondentCount"], cross["overall"]["average"])
                  == (single["answerCount"], single["respondentCount"], single["average"]))
        r = call("POST", f"/api/surveys/{snap['draft_survey_id']}/questions/from-library", owner, json={"questionId": v1["id"]})
        rec.check(s, "把这道题加到第一阶段留下的草稿中", "201（旧草稿可以使用“我的题目”中的题）", r.status_code, r.status_code == 201)
        edit = call("PUT", f"/api/surveys/{demo['id']}/questions/{qs[0]['id']}", owner, json={
            "type": qs[0]["type"], "title": "改标题", "options": qs[0]["options"], "validation": qs[0]["validation"]})
        rec.check(s, "修改已发布旧问卷的题目", "409（第一阶段规则不变：发布后不能修改题目）", edit.status_code, edit.status_code == 409)

    if not keep_db:
        app_db.get_client().drop_database(db_name)   # 应用关闭时释放了客户端，重新获取
    app_db.close_client()
    return rec


def write_report(rec: Recorder, db_name: str) -> None:
    lines = [
        "# 第一阶段 → 第二阶段兼容性验证",
        "",
        f"> 由 `python -m scripts.verify_phase1_compat` 自动生成（{datetime.now():%Y-%m-%d %H:%M}）。"
        f"验证数据库：`{db_name}`（验证前删除重建）。",
        "",
        "**方法**：用 `phase1` 标签的代码（git worktree 临时取出）生成第一阶段的数据，并用第一阶段的接口记录各页面返回的数据；"
        "再切换到当前代码，在同一个数据库上初始化、比较、操作。第一阶段数据包括：示例问卷 Food26（12 道题、5 条跳转、"
        "实名、以最后一次为准、13 份答卷）、一份匿名且“每次都算”的带跳转问卷（3 份答卷）、一份草稿。",
        "",
        f"**结论**：{'全部通过' if rec.ok else '有未通过的项'}（{sum(r[4] for r in rec.rows)} / {len(rec.rows)}）。",
        "",
        "| 阶段 | 操作 | 期望 | 实际 | 结果 |",
        "|---|---|---|---|---|",
    ]
    for section, action, expected, actual, passed in rec.rows:
        actual = actual.replace("|", "\\|").replace("\n", " ")
        if len(actual) > 160:
            actual = actual[:160] + "…"
        lines.append(f"| {section} | {action} | {expected} | {actual} | {'通过' if passed else '**未通过**'} |")
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="第一阶段 → 第二阶段兼容性验证")
    parser.add_argument("--db", default=DEFAULT_DB, help="验证用的数据库名（必须以 _compat 结尾）")
    parser.add_argument("--keep-db", action="store_true", help="验证结束后保留数据库")
    args = parser.parse_args()
    rec = verify(args.db, args.keep_db)
    write_report(rec, args.db)
    print(f"结果已写入 {REPORT.relative_to(ROOT)}：{'全部通过' if rec.ok else '有未通过的项'}")
    sys.exit(0 if rec.ok else 1)


if __name__ == "__main__":
    main()
