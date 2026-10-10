"""modules.auth —— 认证响应组装（登录 / 刷新 / 登出 / 当前用户）。"""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse

from .entity import AuthenticatedUser

from core.responses import json

# refresh token 专用 httpOnly cookie：仅 /api/refresh 使用，JS 读不到。
COOKIE_NAME = "refresh_token"
COOKIE_MAX_AGE = 7 * 24 * 3600  # 7 天，与 refresh 有效期一致


def _set_refresh_cookie(response: JSONResponse, request: Request, token: str, *, expire: bool = False) -> None:
    """写 / 清 ``refresh_token`` cookie（httpOnly + SameSite=Lax，HTTPS 才加 Secure）。"""
    response.set_cookie(
        key=COOKIE_NAME,
        value="" if expire else token,
        max_age=0 if expire else COOKIE_MAX_AGE,
        path="/",
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
    )


def register_success() -> JSONResponse:
    """注册成功响应。"""
    return json({"message": "Registration successful"})


def _user_body(tokens: AuthenticatedUser) -> dict:
    return {"username": tokens.username, "role": tokens.role}


def login_success(request: Request, tokens: AuthenticatedUser) -> JSONResponse:
    """登录成功：access 走响应体（前端存内存）、refresh 走 Set-Cookie。"""
    response = json({
        "message": "Login successful",
        "user": _user_body(tokens),
        "access_token": tokens.access_token,
    })
    _set_refresh_cookie(response, request, tokens.refresh_token)
    return response


def refresh_success(request: Request, tokens: AuthenticatedUser) -> JSONResponse:
    """刷新成功：返回新 access，并轮换下发新 refresh（Set-Cookie）。"""
    response = json({
        "message": "Token refreshed",
        "user": _user_body(tokens),
        "access_token": tokens.access_token,
    })
    _set_refresh_cookie(response, request, tokens.refresh_token)
    return response


def logged_out(request: Request) -> JSONResponse:
    """登出：清除 ``refresh_token`` cookie。"""
    response = json({"message": "Logged out"})
    _set_refresh_cookie(response, request, "", expire=True)
    return response


def me(user: dict) -> JSONResponse:
    """当前登录用户信息（供前端展示/恢复）。"""
    return json({
        "user": {"username": user.get("username", ""), "role": user.get("role", "")},
    })