"""HTTP 认证接口：注册 / 登录 / 刷新 / 登出 / 当前用户（Controller）。

表示层职责仅为：校验请求结构 → 调用 AppService → 交给 views 组装响应。
令牌模型：
- access token 走响应体（前端内存 + ``Authorization`` 头携带）；
- refresh token 走 httpOnly cookie（``/api/refresh`` 轮换）。
"""

from fastapi import APIRouter, Depends, HTTPException, Request

from core.deps import auth_service, current_user
from .dto import Credentials
from . import vo as views

router = APIRouter(prefix="/api", tags=["auth"])


@router.post("/register")
async def register(body: Credentials):
    """处理用户注册。"""
    auth_service.register(body.username, body.password)
    return views.register_success()


@router.post("/login")
async def login(request: Request, body: Credentials):
    """登录：返回 access_token，并用 Set-Cookie 下发 refresh_token。"""
    tokens = auth_service.login(body.username, body.password)
    return views.login_success(request, tokens)


@router.post("/refresh")
async def refresh(request: Request):
    """用 httpOnly cookie 里的 refresh_token 换新令牌对（轮换）。"""
    refresh_token = request.cookies.get(views.COOKIE_NAME)
    if not refresh_token:
        raise HTTPException(status_code=401, detail="missing refresh token")
    tokens = auth_service.refresh(refresh_token)
    return views.refresh_success(request, tokens)


@router.post("/logout")
async def logout(request: Request):
    """登出：吊销该用户全部 refresh 令牌并清除 cookie。"""
    refresh_token = request.cookies.get(views.COOKIE_NAME)
    if refresh_token:
        auth_service.logout(refresh_token)
    return views.logged_out(request)


@router.get("/auth/me")
async def me(user: dict = Depends(current_user)):
    """返回当前登录用户（凭 Authorization 头 / 可选 ?token=）。"""
    return views.me(user)