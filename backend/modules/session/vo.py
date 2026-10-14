"""modules.sessions —— 会话响应组装。"""

from __future__ import annotations

from fastapi.responses import JSONResponse

from core.responses import json, message


def created() -> JSONResponse:
    return message("Session created successfully")


def deleted() -> JSONResponse:
    return message("Session and related data deleted successfully")


def page(payload: dict) -> JSONResponse:
    return json(payload)


def history(entries: list) -> JSONResponse:
    return json({"history": entries})


def admin_deleted(session_id: str) -> JSONResponse:
    """管理端删除结果。"""
    return message(f"会话 {session_id} 已删除")


def history_cleared(session_id: str) -> JSONResponse:
    return message(f"会话 {session_id} 历史已清空")
