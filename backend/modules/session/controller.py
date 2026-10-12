"""会话接口（Controller）：

- 用户端：创建 / 查询（分页）/ 删除本人会话；
- 管理端：列出全部用户会话（分页）/ 查看 / 清空 / 删除任意会话。

业务（列出/历史/删除/清空历史）全部委托 ``SessionService``。
"""

from fastapi import APIRouter, Depends, Query

from core.deps import require_admin, require_auth, session_service
from core.pagination import paginate
from .dto import SessionIdBody
from . import vo as views

# 用户端（/api/*）
router = APIRouter(prefix="/api", tags=["sessions"])

# 管理端（/api/admin/sessions/*，全部要求管理员）
admin_router = APIRouter(prefix="/api/admin/sessions", tags=["admin"])


# ── 用户端 ──

@router.post("/create_session")
def create_session(body: SessionIdBody, user: dict = Depends(require_auth)):
    """创建用户会话。session_id 由请求体提供；username 始终取自 token。

    Raises:
        AppError 409: 会话已存在。
    """
    session_service.create(body.session_id, user["username"], user["user_id"])
    return views.created()


@router.get("/sessions/{username}")
def get_sessions(
    username: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(0, ge=0, le=1000),
    user: dict = Depends(require_auth),
):
    """获取当前登录用户的会话（含首条消息预览，分页；路径 username 仅用于路由兼容）。"""
    sessions = session_service.list_sessions(user["user_id"])
    return views.page(paginate(sessions, page, page_size, key="sessions"))


@router.delete("/sessions/{session_id}")
def delete_session(session_id: str, user: dict = Depends(require_auth)):
    """删除指定会话及其历史记录（仅限本人）。

    Raises:
        SessionAccessDenied: 会话不属于当前用户（由全局处理器返回 403）。
    """
    session_service.delete(session_id, user["user_id"])
    return views.deleted()


# ── 管理端 ──

@admin_router.get("")
def list_all_sessions(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    username: str | None = Query(None),
    keyword: str | None = Query(None),
    user: dict = Depends(require_admin),
):
    """分页列出全部用户会话（可按用户名 / 关键词过滤）。"""
    return views.page(session_service.list_all(
        page=page, page_size=page_size, username=username, keyword=keyword,
    ))


@admin_router.get("/{session_id}/history")
def admin_get_history(session_id: str, user: dict = Depends(require_admin)):
    """读取任意会话的历史记录。"""
    history = session_service.admin_get_history(session_id) or []
    return views.history(history)


@admin_router.post("/{session_id}/history/clear")
def admin_clear_history(session_id: str, user: dict = Depends(require_admin)):
    """清空任意会话的历史（保留会话）。"""
    session_service.admin_clear_history(session_id)
    return views.history_cleared(session_id)


@admin_router.delete("/{session_id}")
def admin_delete_session(session_id: str, user: dict = Depends(require_admin)):
    """删除任意会话及其历史。"""
    session_service.admin_delete(session_id)
    return views.admin_deleted(session_id)