"""对话历史接口：查询与清除（Controller）

用例编排（归属校验/读取/清除）委托 ``modules.SessionService``。
"""

from fastapi import APIRouter, Depends

from core.deps import require_auth, session_service
from .dto import SessionIdBody
from . import vo as views

router = APIRouter(prefix="/api", tags=["history"])


@router.post("/clear_history")
def clear_history(body: SessionIdBody, user: dict = Depends(require_auth)):
    """清除会话历史记录（仅允许操作调用者自己的 session）。

    Raises:
        SessionAccessDenied: 会话不属于当前用户（由全局处理器返回 403）。
    """
    session_service.clear_history(body.session_id, user["user_id"])
    return views.cleared()


@router.get("/history/{session_id}")
def get_history(session_id: str, user: dict = Depends(require_auth)):
    """获取会话历史记录（仅允许读取调用者自己的 session）。"""
    return views.list_(session_service.get_history(session_id, user["user_id"]))
