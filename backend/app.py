# ── FastAPI 应用入口 ──────────────────────────────────────────────
# ruff: noqa: E402, I001  # 先 setpath() 再导入项目模块（顺序有意为之）
"""FastAPI 应用入口：装配（中间件 / 路由 / 静态托管）与生命周期。

启动后端 HTTP 服务；具体接口在 ``modules/*/controller``，横切在 ``core``。
"""

# 设置程序根目录，确保跨工作目录可运行
from config.paths import setpath

setpath()

from contextlib import asynccontextmanager

from fastapi import FastAPI

from core.compositor import get_container
from core.http_errors import register_exception_handlers
from core.middleware import register_middlewares
from infra.logger import configure_third_party_logging, logger
from modules.auth import controller as auth
from modules.config import controller as admin_config
from modules.dashboard import controller as admin_dashboard
from modules.document import controller as documents
from modules.frontend import controller as frontend
from modules.health import controller as health_check
from modules.history import controller as history
from modules.query import controller as query
from modules.session import controller as sessions
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
    logger.info(f"启动完成：容器就绪，超级用户已同步（新建 {created} 个）")
    # 启动异步任务消费入口
    container.task_queue.start_consumers()
    yield


app = FastAPI(lifespan=lifespan)

# 表示层统一异常映射（领域异常 / 请求校验错误 → {"detail": str}）
register_exception_handlers(app)

# 集中注册 HTTP 中间件（CORS + 请求日志/统计）
register_middlewares(app)


# ── 路由注册 ──────────────────────────────────────────────────────

app.include_router(admin_users.router)
app.include_router(admin_config.router)
app.include_router(admin_dashboard.router)
app.include_router(auth.router)
app.include_router(sessions.router)
app.include_router(history.router)
app.include_router(query.router)
app.include_router(documents.router)
app.include_router(documents.media_router)
app.include_router(health_check.router)
app.include_router(frontend.router)

# 前端静态资源挂载（index.html 缺失时自动跳过）
frontend.mount_static(app)


# ── 主入口 ────────────────────────────────────────────────────────

if __name__ == "__main__":
    logger.info("主页地址: http://127.0.0.1:11000 (Press CTRL+RIGHT-CLICK to enter)")
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=11000)
