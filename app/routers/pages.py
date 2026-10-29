"""前端页面（原生 HTML + JavaScript，静态文件位于项目根目录的 static/）。

页面本身是静态的，登录状态保存在浏览器中，由页面脚本判断；未登录时跳转到 /login?next=原地址。
这些路由不出现在接口文档中。
"""
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, RedirectResponse

STATIC_DIR = Path(__file__).resolve().parent.parent.parent / "static"

router = APIRouter(include_in_schema=False)


def _page(name: str) -> FileResponse:
    # 页面会随开发更新，不让浏览器长期缓存
    return FileResponse(STATIC_DIR / name, media_type="text/html; charset=utf-8",
                        headers={"Cache-Control": "no-cache"})


@router.get("/")
def home():
    return RedirectResponse("/surveys")


@router.get("/login")
def login_page():
    return _page("login.html")


@router.get("/surveys")
def surveys_page():
    return _page("surveys.html")


@router.get("/surveys/{survey_id}/edit")
def edit_page(survey_id: str):
    return _page("edit.html")


@router.get("/surveys/{survey_id}/stats")
def stats_page(survey_id: str):
    return _page("stats.html")


# ---------- 第二阶段：题目库 ----------
@router.get("/questions")
def questions_page():
    return _page("questions.html")


@router.get("/questions/{question_id}")
def question_page(question_id: str):
    return _page("question.html")


@router.get("/banks")
def banks_page():
    return _page("banks.html")


@router.get("/banks/{bank_id}")
def bank_page(bank_id: str):
    return _page("bank.html")


@router.get("/survey/{short_code}")
def fill_page(short_code: str):
    """问卷分发链接：<PUBLIC_BASE_URL>/survey/<shortCode>。"""
    return _page("fill.html")
