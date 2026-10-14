"""共享依赖：组合根容器 + 鉴权/会话依赖（全部用 FastAPI Depends）。

system 基于组合根容器组装；应用服务按名取出。

身份/会话的**解析由中间件完成**并缓存在 ``request.state``（``IdentityMiddleware`` /
``SessionMiddleware``）；本模块的依赖函数只做「读取 + 要求」：
  - **守卫式（会抛错）统一 ``require_*``**：``require_auth``（已登录）/ ``require_admin``（管理员）/
    ``require_media_auth``（媒体直链）/ ``require_session_id``（必填会话）
"""

from fastapi import Depends, HTTPException, Request

from core.compositor import get_container
from core.security import extract_bearer

# ── 全局系统实例（Agent 引擎，由组合根装配为单例） ──
system = get_container().get("system")

# ── 应用服务（由组合根装配后按名取出，避免端点直接依赖容器内部结构） ──
auth_service = get_container().get("auth_service")
document_service = get_container().get("document_service")
session_service = get_container().get("session_service")
history_service = get_container().get("history_service")
user_service = get_container().get("user_service")
dashboard_service = get_container().get("dashboard_service")
query_service = get_container().get("query_service")
health_service = get_container().get("health_service")
request_log_service = get_container().get("request_log_service")
request_stats = get_container().get("request_stats")
database_service = get_container().get("database_service")
log_service = get_container().get("log_service")
tool_service = get_container().get("tool_service")
deliverable_service = get_container().get("deliverable_service")
prompt_service = get_container().get("prompt_service")


# ── 鉴权依赖 ──


def require_auth(request: Request) -> dict:
    """要求合法 access token；返回身份 payload。

    token 由 ``IdentityMiddleware`` 解析并写入 ``request.state.user``；
    此处只负责「要求已认证」。

    Raises:
        HTTPException 401: 未认证（缺失 / 非法 access token）。
    """
    payload = getattr(request.state, "user", None)
    if not payload:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return payload


def require_admin(user: dict = Depends(require_auth)) -> dict:
    """要求当前用户为 admin（隐含已登录）。

    Raises:
        HTTPException 403: 角色非 admin。
    """
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Forbidden: admin required")
    return user


# ── 媒体访问鉴权（图片/文件直链） ──


def require_media_auth(request: Request, token: str | None) -> dict:
    """媒体直链鉴权：``?token=`` 查询参数或 ``Authorization`` 头，返回 payload。

    Args:
        request: FastAPI 请求对象。
        token: 查询参数中的 token（可为 None）。

    Returns:
        dict: JWT payload。

    Raises:
        HTTPException 401: token 缺失或无效。
    """
    raw = token or extract_bearer(request)
    if not raw:
        raise HTTPException(status_code=401, detail="missing token")
    payload = auth_service.decode(raw)
    if not payload:
        raise HTTPException(status_code=401, detail="invalid token")
    return payload


# ── 会话 ID 依赖 ──


def require_session_id(request: Request) -> str:
    """上传类接口必填会话 ID（由 ``SessionMiddleware`` 写入 ``request.state.session_id``）。

    Raises:
        HTTPException 400: 缺少 session_id。
    """
    session_id = getattr(request.state, "session_id", None)
    if not session_id:
        raise HTTPException(status_code=400, detail="缺少 session_id")
    return session_id
