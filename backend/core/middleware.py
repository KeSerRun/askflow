"""core.middleware —— FastAPI HTTP 中间件。

职责单一的中间件（注册由外到内：RequestId → 身份 → 会话 → 安全头 → 请求日志 → 调用记录 → GZip → 耗时 → CORS）：
  - ``RequestIdMiddleware``      —— 分配/透传 X-Request-ID，回写响应头，供日志追踪；
  - ``IdentityMiddleware``       —— 尽力解析 access token → request.state.user（只识别、不授权）；
  - ``SessionMiddleware``        —— 解析会话 ID → request.state.session_id；
  - ``SecurityHeadersMiddleware``—— 常规安全响应头；
  - ``LogRequestsMiddleware``    —— 只写访问日志；
  - ``CallRecordMiddleware``     —— 只把 API 调用落库（经 RequestLogService）；
  - ``GZipMiddleware``           —— 响应压缩（自动排除 text/event-stream）；
  - ``TimingMiddleware``         —— 测量耗时 → request.state.elapsed_ms + ``X-Process-Time``。
"""

from __future__ import annotations

import time
import uuid

from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.gzip import GZipMiddleware

from core.concurrency import to_thread_safe
from core.security import decode_access_token, extract_bearer
from infra.util.logger import log_http


class LogRequestsMiddleware(BaseHTTPMiddleware):
    """请求日志中间件：只负责把请求结果写入访问日志。"""

    async def dispatch(self, request, call_next):
        response = await call_next(request)
        # 文件日志是阻塞 IO（RotatingFileHandler + 锁）：丢线程池；失败只告警
        await to_thread_safe(
            log_http, request.method, request.url.path,
            response.status_code, getattr(request.state, "username", "-"),
            getattr(request.state, "request_id", ""),
            getattr(request.state, "elapsed_ms", None), tag="request-log",
        )
        return response


class CallRecordMiddleware(BaseHTTPMiddleware):
    """调用记录中间件：只负责把 API 调用落库（供仪表盘统计）。"""

    def __init__(self, app, service=None, **kwargs):
        """初始化。

        Args:
            app: 下游 ASGI 应用（Starlette 注入）。
            service: ``RequestLogService``（可为 None，则跳过记录）。
        """
        super().__init__(app, **kwargs)
        self._service = service

    async def dispatch(self, request, call_next):
        response = await call_next(request)
        # 仅记录 API 调用，避免静态资源/页面请求刷爆记录表
        if self._service is not None and request.url.path.startswith("/api"):
            await to_thread_safe(
                self._service.record,
                request.method, request.url.path, response.status_code,
                getattr(request.state, "username", "-"),
                user_id=getattr(request.state, "user_id", None),
                latency_ms=getattr(request.state, "elapsed_ms", None), tag="call-record",
            )
        return response


class TimingMiddleware(BaseHTTPMiddleware):
    """测量请求处理耗时：写 ``request.state.elapsed_ms`` 并回写 ``X-Process-Time`` 响应头。"""

    async def dispatch(self, request, call_next):
        t0 = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        request.state.elapsed_ms = elapsed_ms
        response.headers["X-Process-Time"] = str(elapsed_ms)
        return response


class IdentityMiddleware(BaseHTTPMiddleware):
    """尽力解析 ``Authorization: Bearer`` access token → ``request.state.user``（+ 展示用 ``username``）。

    只做「识别」不做「授权」：token 缺失/非法则 user 为 None、username 为 ``-``；是否拦截交给依赖
    （``require_auth`` / ``require_admin``）。供日志 / 调用记录 / 后续限流复用。
    """

    async def dispatch(self, request, call_next):
        user = decode_access_token(extract_bearer(request))
        request.state.user = user
        request.state.username = user.get("username", "-") if user else "-"
        request.state.user_id = user.get("user_id") if user else None
        return await call_next(request)


class SessionMiddleware(BaseHTTPMiddleware):
    """解析会话 ID（``X-Session-ID`` 头 / ``session_id`` cookie）→ ``request.state.session_id``。"""

    async def dispatch(self, request, call_next):
        request.state.session_id = (
            request.headers.get("X-Session-ID")
            or request.cookies.get("session_id")
            or None
        )
        return await call_next(request)


class RequestIdMiddleware(BaseHTTPMiddleware):
    """为每个请求分配/透传 ``X-Request-ID``：写入 request.state 并回写响应头。"""

    async def dispatch(self, request, call_next):
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """给所有响应加常规安全头（已存在则保留）。"""

    _HEADERS = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "SAMEORIGIN",
        "Referrer-Policy": "no-referrer",
        "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
    }

    async def dispatch(self, request, call_next):
        response = await call_next(request)
        for key, value in self._HEADERS.items():
            response.headers.setdefault(key, value)
        return response


def register_middlewares(app, request_log_service=None) -> None:
    """集中注册 HTTP 中间件。

    注册由内到外：CORS → 耗时 → GZip → 调用记录 → 请求日志 → 安全头 → 会话 → 身份 → RequestId。

    Args:
        app: FastAPI 应用。
        request_log_service: 调用记录用例（落库）；为 None 时不记录。
    """
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(TimingMiddleware)
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.add_middleware(CallRecordMiddleware, service=request_log_service)
    app.add_middleware(LogRequestsMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(SessionMiddleware)
    app.add_middleware(IdentityMiddleware)
    app.add_middleware(RequestIdMiddleware)
