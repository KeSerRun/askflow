"""modules.health —— 健康检查响应组装。"""

from __future__ import annotations

from fastapi.responses import JSONResponse

from core.responses import json


def heartbeat() -> JSONResponse:
    """心跳：进程存活即 healthy（无外部依赖检查）。"""
    return json({"status": "healthy"})


def report(result: dict) -> JSONResponse:
    return json(result)
