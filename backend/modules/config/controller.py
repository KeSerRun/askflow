"""管理后台 API - 系统设置（Controller）

- 配置读写走 `.env`（``config.app_config``）；保存后需重启后端生效；
- ``POST /api/admin/restart`` 提供「重启后端服务」：当前进程原地重启。
"""

import os
import sys
import threading

from fastapi import APIRouter, Body, Depends

from config.app_config import config_env_dict, write_env
from config.paths import _project_root
from core.deps import require_admin
from infra.util.logger import logger

from . import vo as views
from .schema import build_schema

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _restart_argv() -> list[str]:
    """构造重启命令：标准入口是 ``python app.py``（本地与容器一致）。"""
    argv0 = sys.argv[0] if sys.argv else ""
    if argv0.lower().endswith(".py"):
        return [sys.executable] + list(sys.argv)
    # 非脚本入口（如 uvicorn app:app）→ 回退到 app.py
    return [sys.executable, os.path.join(_project_root, "app.py")]


def _do_restart() -> None:
    """原地重启：用 os.execv 以新进程映像替换当前进程。

    由后台线程延迟触发，确保「重启」响应已返回客户端。
    """
    argv = _restart_argv()
    logger.info(f"正在重启后端服务: {' '.join(argv)}")
    if sys.platform == "win32":
        # Windows：os.execv 会继承当前进程的 os.environ，而三方库可能已把 .env
        # 灌进去（见 config/paths 的 PYTHON_DOTENV_DISABLED 说明）。这里清掉所有
        # 配置键，让新进程重新从 .env 读取，避免旧值被一代代继承。
        from config.app_config import ENV_TO_FIELD
        for _key in ENV_TO_FIELD:
            os.environ.pop(_key, None)
    try:
        os.execv(argv[0], argv)
    except Exception as e:  # noqa: BLE001
        logger.error(f"重启失败，进程退出: {e}")
        os._exit(1)


@router.get("/config/schema")
def get_config_schema(user: dict = Depends(require_admin)):
    """返回配置项 schema（由 AppConfig 自动派生），前端据此渲染表单。

    Returns:
        JSONResponse: 配置 schema 列表，每项含 key/label/group/type 等字段。
    """
    return views.schema(build_schema())


@router.get("/config")
def get_config(user: dict = Depends(require_admin)):
    """获取当前配置（key=env 名）。

    Returns:
        JSONResponse: 配置字典。
    """
    return views.show(config_env_dict())


@router.put("/config")
def update_config(payload: dict = Body(...), user: dict = Depends(require_admin)):
    """更新配置：写回 `.env`（保存后需重启后端生效）。

    Args:
        payload: 配置键值对字典（key=env 名）。

    Returns:
        JSONResponse: ``{"message": str, "config": dict}``。
    """
    success = write_env(payload)
    return views.updated(success, config_env_dict())


@router.post("/restart")
def restart_backend(user: dict = Depends(require_admin)):
    """重启后端服务：当前进程原地重启（``os.execv``）。

    先返回响应，再由后台线程延迟替换进程映像，使重新加载的 `.env` / 代码生效。
    客户端可轮询 ``/api/health`` 判断服务是否恢复。

    Returns:
        JSONResponse: ``{"message": str}``。
    """
    timer = threading.Timer(0.8, _do_restart)
    timer.daemon = True
    timer.start()
    return views.restarting()
