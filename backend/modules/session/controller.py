"""会话管理接口：创建 / 查询 / 删除（Controller）"""

from fastapi import APIRouter, Depends

from core.deps import current_user, session_service
from .dto import SessionIdBody
from . import vo as views

router = APIRouter(prefix="/api", tags=["sessions"])


@router.post("/create_session")
async def create_session(body: SessionIdBody, user: dict = Depends(current_user)):
    """创建用户会话。session_id 由请求体提供；username 始终取自 token。

    Raises:
        AppError 409: 会话已存在。
    """
    session_service.create(body.session_id, user["username"])
    return views.created()


@router.get("/sessions/{username}")
async def get_sessions(username: str, user: dict = Depends(current_user)):
    """获取当前登录用户的所有会话（含首条消息预览；路径 username 仅用于路由兼容）。"""
    return views.list_(session_service.list_sessions(user["username"]))


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str, user: dict = Depends(current_user)):
    """删除指定会话及其历史记录（仅限本人）。

    Raises:
        SessionAccessDenied: 会话不属于当前用户（由全局处理器返回 403）。
    """
    session_service.delete(session_id, user["username"])
    return views.deleted()
