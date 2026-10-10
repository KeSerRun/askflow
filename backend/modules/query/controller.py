"""RAG 问答查询接口（Controller，支持流式 SSE）

业务编排（风格/工作流、非流式/流式问答、中断）委托 ``modules.QueryService``。
"""

from fastapi import APIRouter, Depends

from core.deps import current_user, query_service

from . import vo as views
from .dto import QueryBody, ResumeBody, SessionIdBody

router = APIRouter(prefix="/api", tags=["query"])


@router.get("/styles")
async def list_styles():
    """返回可用的回答风格列表（由 backend/prompts/style/ 自动发现）。"""
    return views.styles(query_service.styles())


@router.get("/workflows")
async def list_workflows():
    """返回可用工作流列表（由 backend/prompts/workflow/ 自动发现）。"""
    return views.workflows(query_service.workflows())


@router.post("/query")
async def query(body: QueryBody, user: dict = Depends(current_user)):
    """处理用户查询，返回答案。检索范围限定为当前用户自己的分区。

    Args:
        body: 问答请求体（结构由 ``QueryBody`` 校验）。
        user: 当前用户 payload（依赖注入）。

    Returns:
        JSONResponse: 非流式返回 ``{"answer": str}``。
        StreamingResponse: ``body.stream=True`` 时返回 SSE 事件流。
    """
    args = dict(
        username=user["username"],
        session_id=body.session_id,
        question=body.question,
        style=body.style,
        workflow=body.workflow,
    )
    if body.stream:
        return views.sse(query_service.stream(**args))
    return views.answer(await query_service.ask(**args))


@router.post("/query/cancel")
async def cancel_query(body: SessionIdBody, user: dict = Depends(current_user)):
    """中断当前正在进行的生成。"""
    query_service.cancel(body.session_id)
    return views.cancel_ack()


@router.post("/query/resume")
async def resume_query(body: ResumeBody, user: dict = Depends(current_user)):
    """从检查点续跑该会话未完成的生成（断点续跑）。

    Args:
        body: 续跑请求体（session_id + 可选 extra_iterations）。

    Returns:
        JSONResponse: ``{"answer": str}``。
    """
    answer = await query_service.resume(
        session_id=body.session_id,
        extra_iterations=body.extra_iterations,
    )
    return views.answer(answer)
