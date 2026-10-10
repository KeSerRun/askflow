"""core.http_errors —— 表示层统一异常映射（唯一出现 HTTP 状态码的地方）。

把 ``core.errors`` 的语义异常映射为 HTTP 状态码；并处理请求校验错误与未捕获异常。
业务服务层只抛 ``core.errors`` 的语义异常、不感知 HTTP；FastAPI handler 与状态码只在本模块。
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from core.errors import (
    AppError,
    Conflict,
    InvalidCredentials,
    InvalidInput,
    InvalidRefreshToken,
    NotFound,
    PermissionDenied,
    QuotaExceeded,
    Unauthorized,
    UsernameAlreadyExists,
)
from infra.logger import logger

# 语义异常 → HTTP 状态码（dict 有序：从上到下匹配、先中先返；
# 子类如 SessionAccessDenied(继承 PermissionDenied) 靠本顺序命中父类映射）
_STATUS = {
    # 领域专用（优先匹配）
    UsernameAlreadyExists: 400,
    InvalidCredentials: 401,
    InvalidRefreshToken: 401,
    # 通用语义
    QuotaExceeded: 413,
    PermissionDenied: 403,
    NotFound: 404,
    Conflict: 409,
    Unauthorized: 401,
    InvalidInput: 400,
}


def _status_for(exc: AppError) -> int:
    """语义异常 → HTTP 状态码。"""
    for cls, code in _STATUS.items():
        if isinstance(exc, cls):
            return code
    return 400


def _format_validation_error(exc: RequestValidationError) -> str:
    """把 Pydantic 校验错误压成单行字符串（取首条，附带字段名）。"""
    errors = exc.errors()
    if not errors:
        return "Invalid request"
    first = errors[0]
    loc = [str(part) for part in first.get("loc", []) if part not in ("body", "query", "path")]
    msg = first.get("msg", "Invalid request")
    # field_validator 抛 ValueError 时 msg 形如 "Value error, <业务提示>"，去掉前缀。
    if msg.startswith("Value error, "):
        msg = msg[len("Value error, "):]
    return f"{'.'.join(loc)}: {msg}" if loc else msg


def register_exception_handlers(app: FastAPI) -> None:
    """注册全局异常处理器。"""

    @app.exception_handler(AppError)
    async def _app_error(_request: Request, exc: AppError):
        return JSONResponse(status_code=_status_for(exc), content={"detail": str(exc)})

    @app.exception_handler(HTTPException)
    async def _http_exception(_request: Request, exc: HTTPException):
        # 显式注册 FastAPI 的 HTTPException（含 deps 里抛的 400/401/403），统一返回 JSON。
        return JSONResponse(status_code=exc.status_code, content={"detail": str(exc.detail)})

    @app.exception_handler(RequestValidationError)
    async def _request_validation(_request: Request, exc: RequestValidationError):
        # 默认 422 + detail 数组会导致前端 message.error 显示 [object Object]，
        # 这里统一为 400 + 字符串，与既有交互保持一致。
        return JSONResponse(status_code=400, content={"detail": _format_validation_error(exc)})

    @app.exception_handler(Exception)
    async def _unhandled(_request: Request, exc: Exception):
        # 兜底：完整异常只进日志，不把内部信息返回给客户端（防信息泄露）。
        logger.exception(f"未处理异常: {exc}")
        return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})