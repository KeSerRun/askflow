"""modules.sessions —— 会话响应组装。"""

from __future__ import annotations

from fastapi.responses import JSONResponse

from core.responses import json, message


def created() -> JSONResponse:
    return message("Session created successfully")


def list_(sessions) -> JSONResponse:
    return json({"sessions": sessions})


def deleted() -> JSONResponse:
    return message("Session and related data deleted successfully")