"""管理后台 API - 系统设置（Controller）

表单 schema 见 ``modules.config.schema``；配置读写走 `.env`（``config.app_config``）。
"""

from fastapi import APIRouter, Body, Depends

from config import conf
from config.app_config import config_env_dict, write_env
from core.deps import require_admin
from . import vo as views
from .schema import build_schema

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/config/schema")
async def get_config_schema(user: dict = Depends(require_admin)):
    """返回配置项 schema（由 AppConfig 自动派生），前端据此渲染表单。

    Returns:
        JSONResponse: 配置 schema 列表，每项含 key/label/group/type 等字段。
    """
    return views.schema(build_schema())


@router.get("/config")
async def get_config(user: dict = Depends(require_admin)):
    """获取当前配置（key=env 名）。

    Returns:
        JSONResponse: 配置字典。
    """
    return views.show(config_env_dict())


@router.put("/config")
async def update_config(payload: dict = Body(...), user: dict = Depends(require_admin)):
    """更新配置：写回 `.env` 并重新加载（立即生效）。

    Args:
        payload: 配置键值对字典（key=env 名）。

    Returns:
        JSONResponse: ``{"message": str, "config": dict}``。
    """
    success = write_env(payload)
    if success:
        conf.reload_if_changed()
    return views.updated(success, config_env_dict())
