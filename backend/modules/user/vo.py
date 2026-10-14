"""modules.admin.users —— 用户管理响应组装。"""

from __future__ import annotations

from fastapi.responses import JSONResponse

from core.responses import json, message


def page(result: dict) -> JSONResponse:
    """分页用户列表（脱敏：移除 password / id）。"""
    for u in result["items"]:
        u.pop("password", None)
        u.pop("id", None)
    return json(result)


def created(username: str) -> JSONResponse:
    return message(f"用户 '{username}' 创建成功", status_code=201)


def deleted(username: str) -> JSONResponse:
    return message(f"用户 '{username}' 已删除")


def role_updated(username: str, role: str) -> JSONResponse:
    return json({
        "message": f"用户 '{username}' 角色已更新为 {role}",
        "user": {"username": username, "role": role},
    })


def password_reset(username: str) -> JSONResponse:
    return message(f"用户 '{username}' 密码已重置")
