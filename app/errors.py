"""统一错误格式。

所有错误响应都是：
    {"code": "错误码", "message": "中文提示", "errors": [{"field": ..., "message": ...}]}
- code：给程序判断用的英文错误码
- message：给人看的中文提示
- errors：可选，多条字段级错误（字段名，或之后填写问卷时的 questionId）

业务代码中抛出 AppError（或其子类），由这里注册的处理器转换成上述格式。
"""
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


class AppError(Exception):
    """业务错误。"""

    def __init__(self, status_code: int, code: str, message: str,
                 errors: list[dict] | None = None, headers: dict | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.errors = errors
        self.headers = headers


class ValidationFailed(AppError):
    """输入不合法（422），errors 列出每个字段的问题。"""

    def __init__(self, errors: list[dict], message: str = "提交内容不合法"):
        super().__init__(422, "VALIDATION_ERROR", message, errors)


class Unauthorized(AppError):
    """未登录或登录无效（401）。"""

    def __init__(self, code: str = "NOT_AUTHENTICATED", message: str = "请先登录"):
        super().__init__(401, code, message, headers={"WWW-Authenticate": "Bearer"})


class NotFound(AppError):
    """资源不存在（404）。也用于访问别人的资源，不暴露其是否存在。"""

    def __init__(self, code: str, message: str):
        super().__init__(404, code, message)


class Forbidden(AppError):
    """能看到但无权执行该操作（403），如修改别人共享给自己的题目。"""

    def __init__(self, code: str, message: str):
        super().__init__(403, code, message)


class Conflict(AppError):
    """与当前状态或现有数据冲突（409）。"""

    def __init__(self, code: str, message: str, errors: list[dict] | None = None):
        super().__init__(409, code, message, errors)


def error_body(code: str, message: str, errors: list[dict] | None = None) -> dict:
    body = {"code": code, "message": message}
    if errors:
        body["errors"] = errors
    return body


# FastAPI 请求格式错误（缺字段、类型不对、JSON 不合法）的中文提示
_PYDANTIC_MESSAGES = {
    "missing": "缺少必填字段",
    "string_type": "应为字符串",
    "int_type": "应为整数",
    "int_parsing": "应为整数",
    "float_type": "应为数字",
    "float_parsing": "应为数字",
    "bool_type": "应为布尔值",
    "bool_parsing": "应为布尔值",
    "list_type": "应为数组",
    "dict_type": "应为对象",
    "model_type": "应为对象",
    "datetime_type": "应为时间",
    "datetime_parsing": "时间格式不正确",
    "datetime_from_date_parsing": "时间格式不正确",
    "enum": "取值不在允许范围内",
    "literal_error": "取值不在允许范围内",
    "json_invalid": "请求体不是合法的 JSON",
    "extra_forbidden": "不支持该字段",
    "too_long": "数量超出上限",
    "greater_than_equal": "不能小于 {ge}",
    "less_than_equal": "不能大于 {le}",
    "timezone_aware": "时间必须带时区（如 2026-11-30T23:59:59+08:00 或以 Z 结尾的 UTC 时间）",
}


def _field_name(loc: tuple) -> str:
    # loc 形如 ("body", "username")，去掉开头的位置标记
    parts = [str(p) for p in loc if p not in ("body", "query", "path", "header")]
    return ".".join(parts) or "body"


def _validation_item(e: dict) -> dict:
    loc = tuple(e.get("loc", ()))
    if e.get("type") == "json_invalid":
        # 此时 loc 为 ("body", 出错的字符下标)，下标不是字段名，放进提示文字里（下标从 0 开始，提示从 1 开始）
        message = "请求体不是合法的 JSON"
        if len(loc) > 1 and isinstance(loc[1], int):
            message += f"（第 {loc[1] + 1} 个字符附近）"
        return {"field": "body", "message": message}
    message = _PYDANTIC_MESSAGES.get(e.get("type"), "格式不正确")
    try:
        message = message.format(**(e.get("ctx") or {}))  # 如“不能大于 {le}”
    except (KeyError, IndexError):
        pass
    return {"field": _field_name(loc), "message": message}


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError):
        return JSONResponse(status_code=exc.status_code,
                            content=error_body(exc.code, exc.message, exc.errors),
                            headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _request_validation(request: Request, exc: RequestValidationError):
        errors = [_validation_item(e) for e in exc.errors()]
        return JSONResponse(status_code=422,
                            content=error_body("VALIDATION_ERROR", "提交内容不合法", errors))

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException):
        code, message = {
            # 例如请求体不是合法的 UTF-8，Starlette 在解析阶段就会返回 400
            400: ("BAD_REQUEST", "请求体无法解析，请使用 UTF-8 编码的 JSON"),
            404: ("NOT_FOUND", "请求的资源不存在"),
            405: ("METHOD_NOT_ALLOWED", "不支持该请求方法"),
        }.get(exc.status_code, ("HTTP_ERROR", str(exc.detail)))
        return JSONResponse(status_code=exc.status_code, content=error_body(code, message),
                            headers=getattr(exc, "headers", None))

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception):
        logger.exception("未处理的异常")
        return JSONResponse(status_code=500, content=error_body("INTERNAL_ERROR", "服务器内部错误"))
