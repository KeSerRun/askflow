"""管理后台 API - 数据管理（向量库 / 文档）Controller。

全部接口要求管理员（``require_admin``）。业务在 ``DatabaseService``。
"""

from typing import List

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile

from core.app_errors import AppError
from core.concurrency import to_thread
from core.deps import database_service, require_admin
from .dto import MdViewActionBody
from . import vo as views

router = APIRouter(prefix="/api/admin/database", tags=["admin"])


@router.get("")
def get_stats(user: dict = Depends(require_admin)):
    """向量库统计概览（切块/向量/分区/来源/类型/嵌入信息）。"""
    return views.ok(database_service.stats())


@router.get("/chunks")
def get_chunks(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    source: str | None = Query(None),
    chunk_type: str | None = Query(None),
    query_text: str | None = Query(None),
    user: dict = Depends(require_admin),
):
    """切块详情列表（分页 + 过滤）。"""
    return views.ok(database_service.chunks(
        page=page, page_size=page_size,
        source=source, chunk_type=chunk_type, query_text=query_text,
    ))


@router.get("/system_docs")
def list_system_docs(
    page: int = Query(1, ge=1),
    page_size: int = Query(0, ge=0, le=500),
    user: dict = Depends(require_admin),
):
    """列出已入库的系统文档（向量库 ``__system__`` 分区按 source 聚合，分页）。"""
    return views.ok(database_service.list_system_docs(page=page, page_size=page_size))


@router.get("/system_files")
def list_system_raw_files(
    page: int = Query(1, ge=1),
    page_size: int = Query(0, ge=0, le=500),
    user: dict = Depends(require_admin),
):
    """列出 MinIO ``uploads/__system__/`` 原始文件（上传队列，含未入库文件，分页）。"""
    return views.ok(database_service.list_system_raw_files(page=page, page_size=page_size))


@router.get("/md_view")
def md_view(
    source: str = Query(...),
    user: dict = Depends(require_admin),
):
    """MD 切块可视化：按页展示文档 md，标记每页内的切块边界。

    Raises:
        HTTPException 400: source 缺失。
    """
    try:
        return views.ok(database_service.md_view(source))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/parent")
def parent_text(
    id: str = Query(..., description="父块 id（md5(父块全文)）"),
    user: dict = Depends(require_admin),
):
    """按父块 id 返回父块（未切分的正文整段）全文。"""
    try:
        return views.ok(database_service.chunk_parent_text(id))
    except AppError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/upload")
async def upload_system(files: List[UploadFile] = File(...), user: dict = Depends(require_admin)):
    """上传系统级文档（后台向量化，立即返回任务 ID）。"""
    files_data = [(f.filename, await f.read(), f.content_type) for f in files]
    return views.ok(await to_thread(database_service.upload_system, files_data))


@router.get("/upload/task/{task_id}")
def upload_task(task_id: str, user: dict = Depends(require_admin)):
    """按任务 ID 查询上传详情（含逐文件状态）。"""
    try:
        return views.ok(database_service.upload_task(task_id))
    except KeyError:
        raise HTTPException(status_code=404, detail=f"任务不存在: {task_id}")


@router.post("/mdview/embed")
def mdview_embed(body: MdViewActionBody, user: dict = Depends(require_admin)):
    """文档视图手动调整：把未嵌入的指定块嵌入向量库。"""
    try:
        return views.ok(database_service.mdview_embed(body.source, body.page, body.block_idx))
    except AppError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/mdview/remove")
def mdview_remove(body: MdViewActionBody, user: dict = Depends(require_admin)):
    """文档视图手动调整：把已嵌入块的向量从库里移除。"""
    try:
        return views.ok(database_service.mdview_remove(body.source, body.page, body.block_idx))
    except AppError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/delete")
def delete_document(
    source: str = Query(...),
    user: dict = Depends(require_admin),
):
    """删除指定文档（向量 + 原文件 + chunk 产物）。"""
    database_service.delete(source)
    return views.deleted(f"文档 '{source}' 已删除")


@router.delete("/system_file")
def delete_system_raw_file(
    source: str = Query(...),
    user: dict = Depends(require_admin),
):
    """仅删除 ``__system__`` 分区下的原始文件；向量与切块产物保留。"""
    return views.ok(database_service.delete_raw_file(source))
