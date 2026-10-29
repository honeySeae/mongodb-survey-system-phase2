"""FastAPI 应用入口。

启动：uvicorn app.main:app --reload
挂载各模块的接口路由（auth、surveys、questions、question_library、banks、fill、stats、meta）、前端页面路由和静态资源。
"""
import mimetypes
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app import db
from app.db_schema import ensure_schema
from app.errors import register_error_handlers
from app.routers import auth, banks, fill, meta, pages, question_library, questions, stats, surveys


# Windows 上 mimetypes 会读取注册表，部分机器把 .js 识别为 text/plain，浏览器会拒绝执行模块脚本。
# 显式登记，保证各平台一致。
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/javascript", ".mjs")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("image/svg+xml", ".svg")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时确保集合、校验规则和索引就绪（幂等）；MongoDB 不可用时直接启动失败，便于发现问题
    ensure_schema(db.get_db())
    yield
    db.close_client()


def create_app() -> FastAPI:
    app = FastAPI(title="在线问卷系统", version="0.1.0", lifespan=lifespan)
    register_error_handlers(app)
    app.include_router(auth.router)
    app.include_router(surveys.router)
    app.include_router(questions.router)
    app.include_router(question_library.router)
    app.include_router(banks.router)
    app.include_router(fill.router)
    app.include_router(stats.router)
    app.include_router(meta.router)
    app.include_router(pages.router)
    # 前端静态资源（CSS、JS）；页面 HTML 由 pages 路由返回
    app.mount("/static", StaticFiles(directory=pages.STATIC_DIR), name="static")

    @app.get("/api/health", tags=["system"])
    def health():
        """健康检查：服务是否在运行、数据库是否可连接。"""
        if db.ping():
            return {"status": "ok", "database": "ok"}
        return JSONResponse(status_code=503, content={"status": "error", "database": "unavailable"})

    return app


app = create_app()
