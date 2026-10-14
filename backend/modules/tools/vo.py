"""modules.tools.vo —— 工具管理响应组装。"""

from __future__ import annotations

from fastapi.responses import JSONResponse

from core.responses import json, message


def ok(payload) -> JSONResponse:
    return json(payload)


def deleted(name: str) -> JSONResponse:
    return message(f"工具 {name} 已删除")
