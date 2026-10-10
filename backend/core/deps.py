"""共享依赖：组合根容器 + 鉴权/会话依赖（全部用 FastAPI Depends）。

system 基于组合根容器组装；应用服务按名取出。
  - get_jwt          统一取 JWT（?token= / Bearer 头 / token cookie）
  - current_user     要求合法 JWT（Bearer 或 cookie），返回 payload
  - require_admin    要求 admin（隐含已登录）
  - media_identity   媒体直链鉴权（get_jwt + 校验）
  - session_id_required / optional_session_id   会话 ID（header 或 cookie）
"""

from typing import Optional

import jwt
from fastapi import Depends, Header, HTTPException, Request

from config import conf
from infra.logger import logger
from core.compositor import get_container


# ── 全局系统实例（Agent 引擎，由组合根装配为单例） ──
system = get_container().get("system")

# ── 应用服务（由组合根装配后按名取出，避免端点直接依赖容器内部结构） ──
auth_service = get_container().get("auth_service")
document_service = get_container().get("document_service")
storage_service = get_container().get("storage_service")
session_service = get_container().get("session_service")
user_service = get_container().get("user_service")
dashboard_service = get_container().get("dashboard_service")
query_service = get_container().get("query_service")


# ── 鉴权依赖 ──


def get_jwt(request: Request, token: str | None = None) -> str | None:
    """统一取原始 JWT：``?token=`` 查询参数 → ``Authorization: Bearer`` 头。

    注意：这里的 token **只能是 access token**（refresh token 是不透明随机串，仅 /api/refresh 可用）。

    Args:
        request: FastAPI 请求对象。
        token: 查询参数中的 token（供图片/文件直链等无法带头的场景使用）。

    Returns:
        str | None: 原始 JWT 字符串；找不到则返回 None。
    """
    raw = token
    header = request.headers.get("Authorization")
    if not raw and header and header.startswith("Bearer "):
        raw = header.split(" ", 1)[1]
    return raw


def current_user(request: Request) -> dict:
    """要求合法 access token（``Authorization: Bearer`` 头或 ``?token=``），返回 payload。

    Raises:
        HTTPException 401: token 缺失、格式错误或 JWT 校验失败。
    """
    raw = get_jwt(request)
    if not raw:
        raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        payload = jwt.decode(raw.encode("utf-8"), conf.auth_jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError as e:
        logger.warning(f"JWT 校验失败: {e}")
        raise HTTPException(status_code=401, detail="Unauthorized")

    if not payload.get("username") or payload.get("type") != "access":
        raise HTTPException(status_code=401, detail="Unauthorized")
    return payload


def require_admin(user: dict = Depends(current_user)) -> dict:
    """要求当前用户为 admin（隐含已登录）。

    Raises:
        HTTPException 403: 角色非 admin。
    """
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Forbidden: admin required")
    return user


# ── 媒体访问鉴权（图片/文件直链） ──


def media_identity(request: Request, token: str | None) -> dict:
    """从 ``?token=`` / ``Authorization`` 头 / ``token`` cookie 解析并校验 JWT（供图片/文件直链访问）。

    Args:
        request: FastAPI 请求对象。
        token: 查询参数中的 token（可为 None）。

    Returns:
        dict: JWT payload。

    Raises:
        HTTPException 401: token 缺失或无效。
    """
    raw = get_jwt(request, token)
    if not raw:
        raise HTTPException(status_code=401, detail="missing token")
    payload = auth_service.decode(raw)
    if not payload:
        raise HTTPException(status_code=401, detail="invalid token")
    return payload


# ── 会话 ID 依赖 ──


def session_id_required(
    request: Request,
    x_session_id: str = Header(None, alias="X-Session-ID"),
) -> str:
    """上传类接口必填会话 ID（``X-Session-ID`` 头或 ``session_id`` cookie）。

    Raises:
        HTTPException 400: 缺少 session_id。
    """
    # 从请求头以及cookies中获取会话ID
    session_id = x_session_id or request.cookies.get("session_id")
    if not session_id:
        raise HTTPException(status_code=400, detail="缺少 session_id")
    return session_id


def optional_session_id(
    request: Request,
    x_session_id: str = Header(None, alias="X-Session-ID"),
) -> Optional[str]:
    """可选会话 ID（``X-Session-ID`` 头或 ``session_id`` cookie）。"""
    return x_session_id or request.cookies.get("session_id")
