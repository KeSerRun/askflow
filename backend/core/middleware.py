"""core.middleware —— FastAPI HTTP 中间件（请求日志 + 运行统计）。"""

from __future__ import annotations

from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from core import runtime
from infra.logger import log_http


class LogRequestsMiddleware(BaseHTTPMiddleware):
    """请求日志 + 运行统计中间件（注册见 app.py：``app.add_middleware(...)``）。"""

    async def dispatch(self, request, call_next):
        response = await call_next(request)
        username = "-"
        if getattr(request.state, "user", None):
            username = request.state.user.get("username", "-")
        log_http(request.method, request.url.path, response.status_code, username)
        runtime.request_stats.record(request.method, request.url.path, response.status_code)
        return response


def register_middlewares(app) -> None:
    """集中注册 HTTP 中间件（CORS + 请求日志/统计）。

    注意：Starlette 先注册的在内侧；先 CORS 再日志，保持日志在最外层。
    """
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(LogRequestsMiddleware)
