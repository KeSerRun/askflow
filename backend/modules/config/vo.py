"""modules.admin.config —— 配置管理响应组装。"""

from __future__ import annotations

from fastapi.responses import JSONResponse

from core.responses import json


def schema(schema_list: list) -> JSONResponse:
    return json(schema_list)


def show(config: dict) -> JSONResponse:
    return json(config)


def updated(success: bool, config: dict) -> JSONResponse:
    return json({
        "message": "配置更新成功" if success else "未检测到变更",
        "config": config,
    })