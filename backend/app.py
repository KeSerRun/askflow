# ── FastAPI 应用入口 ──────────────────────────────────────────────
# ruff: noqa: E402, I001  # 先 setpath() 再导入项目模块（顺序有意为之）
"""FastAPI 应用入口：装配（中间件 / 路由 / 静态托管）与生命周期。

启动后端 HTTP 服务；具体接口在 ``modules/*/controller``，横切在 ``core``。
"""

# 禁用三方库（pymilvus 等）导入时的 python-dotenv 加载：它们会把 .env 灌进
# os.environ，而本项目取值链是 os.environ > .env，会因此遮蔽后台对 .env 的修改
# （该污染还会随 os.execv 重启被继承）。必须早于任何相关三方库导入。
import os as _os

_os.environ.setdefault("PYTHON_DOTENV_DISABLED", "1")

# 设置程序根目录，确保跨工作目录可运行
from config.paths import setpath

setpath()

from contextlib import asynccontextmanager

from fastapi import FastAPI

import uvicorn

from core.compositor import get_container
from core.http_errors import register_exception_handlers
from core.middleware import register_middlewares
from infra.util.logger import configure_third_party_logging, logger
from modules.auth import controller as auth
from modules.config import controller as admin_config
from modules.dashboard import controller as admin_dashboard
from modules.database import controller as admin_database
from modules.deliverable import controller as deliverables
from modules.document import controller as documents
from modules.frontend import controller as frontend
from modules.health import controller as health_check
from modules.history import controller as history
from modules.logger import controller as admin_logs
from modules.prompt import controller as admin_prompts
from modules.query import controller as query
from modules.session import controller as sessions
from modules.tools import controller as admin_tools
from modules.user import controller as admin_users

# ── 应用初始化 ────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """应用生命周期管理：装配容器 + 同步超管 + 注入彩色日志到 uvicorn。"""
    # 配置日志格式
    configure_third_party_logging()
    # 启动装配：组合根容器
    container = get_container()
    # 创建超级用户
    created = container.user_service.ensure_admins(
        container.config.auth_superuser_users,
        container.config.auth_superuser_passwords,
    )
    # 注意：uvicorn 的顺序是「先跑 lifespan（这里）→ 再 bind 端口」。所以此处只能
    # 说「初始化完成」；真正开始监听的提示由 __main__ 的 _Server.startup 钩子打印。
    logger.info(f"初始化完成：容器就绪，超级用户已同步（新建 {created} 个），即将监听端口")
    yield


app = FastAPI(lifespan=lifespan)

# 表示层统一异常映射（领域异常 / 请求校验错误 → {"detail": str}）
register_exception_handlers(app)

# 集中注册 HTTP 中间件（CORS + 调用记录 + 请求日志）
# 调用记录落库策略由中间件按 APP_ENV 决定：生产只落 HTTP>=300，开发全记
register_middlewares(
    app,
    request_log_service=get_container().get("request_log_service"),
    request_stats=get_container().get("request_stats"),
)


# ── 路由注册 ──────────────────────────────────────────────────────

app.include_router(admin_users.router)
app.include_router(admin_tools.router)
app.include_router(admin_config.router)
app.include_router(admin_dashboard.router)
app.include_router(admin_database.router)
app.include_router(deliverables.admin_router)
app.include_router(deliverables.router)
app.include_router(auth.router)
app.include_router(sessions.router)
app.include_router(sessions.admin_router)
app.include_router(admin_logs.router)
app.include_router(admin_prompts.router)
app.include_router(history.router)
app.include_router(query.router)
app.include_router(documents.router)
app.include_router(documents.media_router)
app.include_router(health_check.router)
app.include_router(frontend.router)

# 前端静态资源挂载（index.html 缺失时自动跳过）
frontend.mount_static(app)


# ── 主入口 ────────────────────────────────────────────────────────

# 并发调优：放宽 FastAPI 同步接口的线程池上限（anyio 默认 40 太紧）。
# APP_THREAD_POOL=并发线程数（默认 200，最小 40）；
# APP_WORKERS=进程数（默认 1；>1 时用模块串启动。注意：进程各自持有内存态
#             （工具注册/目标/任务清单/checkpoint），多进程可能影响跨请求一致性）。
import os as _os

from config import conf

try:
    import anyio  # fastapi 依赖，必在
    _limiter = anyio.to_thread.current_default_thread_limiter()
    _limiter.total_tokens(max(int(conf.app_thread_pool or 200), 40))
except Exception:  # noqa: BLE001
    pass


def _wait_bind_free(port: int, timeout: float = 30.0) -> None:
    """等待端口可绑定后再启动服务。

    Windows 上「重启后端服务」（``os.execv``）会让新旧进程短暂并存，新进程可能
    先于旧进程释放端口而抢绑失败（EADDRINUSE）。这里轮询直到端口释放。
    干净启动时端口本就空闲，首次探测即通过，无额外开销。
    """
    import socket
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            probe.bind(("0.0.0.0", port))
            return
        except OSError:
            time.sleep(0.3)
        finally:
            probe.close()


class _ReadyServer(uvicorn.Server):
    """在**端口绑定成功之后**才打印就绪提示。

    ``Server.startup()`` 内部顺序：lifespan.startup → 建 socket 并 bind →
    打印 "Uvicorn running on ..." → ``self.started = True``。绑定失败（EADDRINUSE）
    会直接抛异常，后面的日志不会打——所以这里能打印，就说明真的在监听了。
    """

    def __init__(self, config, ready_port: int):
        super().__init__(config)
        self._ready_port = ready_port

    async def startup(self, sockets=None):
        await super().startup(sockets=sockets)
        if self.started:
            logger.info(
                f"服务已就绪：主页地址 http://127.0.0.1:{self._ready_port} "
                f"(Press CTRL+RIGHT-CLICK to enter)"
            )


if __name__ == "__main__":
    import os as _os2

    # 端口：优先 PORT 环境变量（便于换端口解决浏览器权限记录），默认 11000
    _port = int(_os2.environ.get("PORT", "11000"))
    _wait_bind_free(_port)
    _workers = int(conf.app_workers or 1)
    try:
        if _workers > 1:
            # 多 worker 走 supervisor + import string，拿不到 Server 实例，
            # 由 uvicorn 自己为每个子进程打印 "Uvicorn running on ..."。
            uvicorn.run("app:app", host="0.0.0.0", port=_port, workers=_workers)
        else:
            _ReadyServer(uvicorn.Config(app, host="0.0.0.0", port=_port), _port).run()
    except KeyboardInterrupt:
        # Ctrl+C 正常停机：uvicorn 已打印 "Finished server process"，无需抛回溯
        logger.info("接收到中断信号，服务已停止")
