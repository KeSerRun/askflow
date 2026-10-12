"""modules.database.vo —— 数据管理响应组装。"""

from __future__ import annotations

from fastapi.responses import JSONResponse

from core.responses import json, message


def ok(payload: dict) -> JSONResponse:
    """通用 JSON 响应。"""
    return json(payload)


def deleted(text: str) -> JSONResponse:
    """操作成功消息响应。"""
    return message(text)
