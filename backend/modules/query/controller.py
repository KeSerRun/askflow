"""RAG 问答查询接口（Controller，支持流式 SSE）

业务编排（风格、非流式/流式问答、中断）委托 ``modules.QueryService``。
"""

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile

from core.concurrency import to_thread
from core.deps import query_service, require_auth

from . import vo as views
from .dto import QueryBody, ResumeBody, SessionIdBody

router = APIRouter(prefix="/api", tags=["query"])


@router.get("/styles")
def list_styles():
    """返回可用的回答风格列表（由 backend/prompts/style/ 自动发现）。"""
    return views.styles(query_service.styles())


@router.get("/workflows")
def list_workflows():
    """返回可用的工作流列表（由 backend/prompts/workflow/ 自动发现）。"""
    return views.workflows(query_service.workflows())


@router.post("/query")
async def query(body: QueryBody, user: dict = Depends(require_auth)):
    """处理用户查询，返回答案。检索范围限定为当前用户自己的分区。

    Args:
        body: 问答请求体（结构由 ``QueryBody`` 校验）。
        user: 当前用户 payload（依赖注入）。

    Returns:
        JSONResponse: 非流式返回 ``{"answer": str}``。
        StreamingResponse: ``body.stream=True`` 时返回 SSE 事件流。
    """
    if not body.question.strip():
        raise HTTPException(status_code=400, detail="question 不能为空：纯图片不支持，请附上文字说明")
    args = dict(
        user_id=user["user_id"],
        session_id=body.session_id,
        question=body.question,
        style=body.style,
        workflow=body.workflow,
        images=body.images,
    )
    if body.stream:
        return views.sse(query_service.stream(**args))
    return views.answer(await query_service.ask(**args))


@router.post("/query/upload_image")
async def upload_image(
    file: UploadFile = File(...),
    session_id: str = Query(""),
    user: dict = Depends(require_auth),
):
    """上传剪贴板/本地的图片，返回对象键（供 search_knowledge_base 的 images 参数图文检索）。

    图片存放在 ``sessions/{user_id}/{session_id}/query_img/``，随会话删除时一并清理。
    """
    data = await file.read()
    try:
        key = await to_thread(
            query_service.upload_query_image,
            user_id=user["user_id"], session_id=session_id, data=data,
            filename=file.filename or "pasted.png",
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(e))
    return {"key": key}


@router.post("/query/cancel")
def cancel_query(body: SessionIdBody, user: dict = Depends(require_auth)):
    """中断当前正在进行的生成。"""
    query_service.cancel(body.session_id)
    return views.cancel_ack()


@router.post("/query/resume")
async def resume_query(body: ResumeBody, user: dict = Depends(require_auth)):
    """从检查点续跑该会话未完成的生成（断点续跑 / 澄清后带 answer 继续）。

    Args:
        body: 续跑请求体（session_id + 可选 answer / extra_iterations / stream）。

    Returns:
        StreamingResponse: ``body.stream=True`` 时返回 SSE 事件流。
        JSONResponse: 否则返回 ``{"answer": str}``。
    """
    if body.stream:
        return views.sse(query_service.stream_resume(
            session_id=body.session_id,
            answer=body.answer,
            extra_iterations=body.extra_iterations,
        ))
    answer = await query_service.resume(
        session_id=body.session_id,
        answer=body.answer,
        extra_iterations=body.extra_iterations,
    )
    return views.answer(answer)
