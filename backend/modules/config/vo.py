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
        "message": "配置已保存，重启后端后生效" if success else "未检测到变更",
        "config": config,
    })


def restarting() -> JSONResponse:
    return json({"message": "后端正在重启，请稍候…"})
