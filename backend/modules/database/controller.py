"""管理后台 API - 数据管理（向量库 / 文档）Controller。

全部接口要求管理员（``require_admin``）。业务在 ``DatabaseService``。
"""


from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel

from core.app_errors import AppError
from core.concurrency import to_thread
from core.deps import database_service, require_admin

from . import vo as views
from .dto import MdViewActionBody


class KnowledgeBaseCreate(BaseModel):
    name: str
    description: str = ""


class KnowledgeBaseUpdate(BaseModel):
    new_name: str | None = None
    description: str | None = None


router = APIRouter(prefix="/api/admin/database", tags=["admin"])


@router.get("")
def get_stats(user: dict = Depends(require_admin)):
    """向量库统计概览（切块/向量/分区/来源/类型/嵌入信息）。"""
    return views.ok(database_service.stats())


# ── 知识库管理 ──

@router.get("/knowledge_bases")
def list_knowledge_bases(
    page: int = Query(1, ge=1),
    page_size: int = Query(0, ge=0, le=200),
    keyword: str | None = Query(None, description="按名称/描述模糊搜索"),
    user: dict = Depends(require_admin),
):
    """列出知识库（分区）及其统计，支持分页与模糊搜索。"""
    return views.ok(database_service.list_knowledge_bases_page(
        page=page, page_size=page_size, keyword=keyword,
    ))


@router.post("/knowledge_bases")
def create_knowledge_base(body: KnowledgeBaseCreate, user: dict = Depends(require_admin)):
    """创建知识库。"""
    try:
        return views.ok(database_service.create_knowledge_base(body.name, body.description))
    except AppError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/knowledge_bases/{name}")
def update_knowledge_base(name: str, body: KnowledgeBaseUpdate, user: dict = Depends(require_admin)):
    """重命名/更新知识库。"""
    try:
        return views.ok(database_service.update_knowledge_base(name, body.new_name, body.description))
    except AppError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/knowledge_bases/{name}")
def delete_knowledge_base(name: str, user: dict = Depends(require_admin)):
    """删除知识库及其所有数据。"""
    try:
        return views.ok(database_service.delete_knowledge_base(name))
    except AppError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/chunks")
def get_chunks(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    source: str | None = Query(None),
    partition: str | None = Query(None, description="按知识库过滤"),
    chunk_type: str | None = Query(None),
    query_text: str | None = Query(None),
    user: dict = Depends(require_admin),
):
    """切块详情列表（分页 + 过滤）。"""
    return views.ok(database_service.chunks(
        page=page, page_size=page_size,
        source=source, partition=partition,
        chunk_type=chunk_type, query_text=query_text,
    ))


@router.get("/system_docs")
def list_system_docs(
    partition: str | None = Query(None, description="知识库名；留空返回全部知识库"),
    keyword: str | None = Query(None, description="按文件名/知识库名模糊搜索"),
    page: int = Query(1, ge=1),
    page_size: int = Query(0, ge=0, le=500),
    user: dict = Depends(require_admin),
):
    """列出已入库文档（含所属知识库与切块数，支持模糊搜索与分页）。"""
    return views.ok(database_service.list_system_docs(
        partition=partition, keyword=keyword, page=page, page_size=page_size))


@router.get("/system_files")
def list_system_raw_files(
    partition: str | None = Query(None, description="知识库名；留空查 __system__"),
    page: int = Query(1, ge=1),
    page_size: int = Query(0, ge=0, le=500),
    user: dict = Depends(require_admin),
):
    """列出该知识库 MinIO ``uploads/{partition}/`` 下的原始文件（含未入库，分页）。"""
    return views.ok(database_service.list_system_raw_files(
        partition=partition, page=page, page_size=page_size))


@router.get("/md_view")
def md_view(
    source: str = Query(...),
    partition: str | None = Query(None, description="知识库名"),
    user: dict = Depends(require_admin),
):
    """MD 切块可视化：按页展示文档 md，标记每页内的切块边界。

    Raises:
        HTTPException 400: source 缺失。
    """
    try:
        return views.ok(database_service.md_view(source, partition))
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
async def upload_system(
    files: list[UploadFile] = File(...),
    partition: str = Query(..., description="知识库名称（必填，无默认知识库）"),
    user: dict = Depends(require_admin),
):
    """上传文档到指定知识库（后台向量化，立即返回任务 ID）。"""
    files_data = [(f.filename, await f.read(), f.content_type) for f in files]
    return views.ok(await to_thread(database_service.upload_system, files_data, partition))


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
        return views.ok(database_service.mdview_embed(
            body.source, body.page, body.block_idx, getattr(body, "partition", None)))
    except AppError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/mdview/remove")
def mdview_remove(body: MdViewActionBody, user: dict = Depends(require_admin)):
    """文档视图手动调整：把已嵌入块的向量从库里移除。"""
    try:
        return views.ok(database_service.mdview_remove(
            body.source, body.page, body.block_idx, getattr(body, "partition", None)))
    except AppError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/delete")
def delete_document(
    source: str = Query(...),
    partition: str | None = Query(None, description="知识库名"),
    user: dict = Depends(require_admin),
):
    """删除指定文档（向量 + 原文件 + chunk 产物）。"""
    database_service.delete(source, partition)
    return views.deleted(f"文档 '{source}' 已删除")


@router.delete("/system_file")
def delete_system_raw_file(
    source: str = Query(...),
    partition: str | None = Query(None, description="知识库名"),
    user: dict = Depends(require_admin),
):
    """仅删除该知识库下的原始文件；向量与切块产物保留。"""
    return views.ok(database_service.delete_raw_file(source, partition))
