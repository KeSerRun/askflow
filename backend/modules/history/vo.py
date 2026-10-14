"""modules.history —— 历史响应组装。"""

from __future__ import annotations

from fastapi.responses import JSONResponse

from core.responses import json, message


def cleared() -> JSONResponse:
    return message("Session history cleared successfully")


def list_(history) -> JSONResponse:
    return json({"history": history})
