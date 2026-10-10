"""文档管理接口：上传 / 向量化 / 列出 / 清除 / 下载（Controller）

业务（文件名校验/保存/入库/清理/路径与图片解析/进度编排）全部在
``modules.DocumentService``；本层只做 HTTP：读取 multipart、鉴权、组装响应。
"""

import glob
import mimetypes
from pathlib import Path
from typing import List

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse

from config import conf
from core.deps import (
    current_user,
    document_service,
    media_identity,
    optional_session_id,
    session_id_required,
    storage_service,
)
from .dto import AddDocumentsBody, SourcesBody
from . import vo as views
from core.responses import sse_event

router = APIRouter(prefix="/api", tags=["documents"])


# ── 媒体直链（LLM 输出的 /images/{hash}.jpg） ──

media_router = APIRouter(prefix="/images", tags=["media"])


@media_router.get("/{img_name:path}")
async def serve_root_image(request: Request, img_name: str, token: str = Query(None)):
    """搜索并返回图片。处理 LLM 输出的 /images/hash.jpg 格式。

    Raises:
        HTTPException 401: token 缺失或无效（media_identity）。
        HTTPException 404: 图片未找到。
    """
    media_identity(request, token)

    img_name = img_name.rstrip("/")
    if img_name.startswith("images/"):
        img_name = img_name[7:]

    search_pattern = str(Path(conf.storage_data_dir) / "uploads" / "*" / "chunk_out" / "*" / "images" / img_name)
    candidates = glob.glob(search_pattern)
    if not candidates:
        raise HTTPException(status_code=404, detail="image not found")

    target = Path(candidates[0]).resolve()
    media_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
    return FileResponse(path=str(target), media_type=media_type)


def _sse(events):
    """把服务产出的 dict 事件流格式化为 SSE 行。"""
    for event in events:
        yield sse_event(event)


@router.post("/add_documents")
async def add_documents(body: AddDocumentsBody, user: dict = Depends(current_user)):
    """添加文档到检索器（仅作用于自己的分区）。

    Raises:
        AppError 403: 路径穿越。
        AppError 400: 路径不存在。
    """
    document_service.add_from_path(user["username"], body.documents_path)
    return views.added()


@router.post("/clear_documents")
async def clear_documents(
    session_id: str | None = Depends(optional_session_id),
    user: dict = Depends(current_user),
):
    """清除当前用户自己的所有文档（向量 + 原文件 + chunk 产物）。"""
    document_service.clear_all(user["username"], session_id=session_id)
    return views.cleared()


@router.post("/clear_chosen_documents")
async def clear_chosen_documents(
    body: SourcesBody,
    session_id: str | None = Depends(optional_session_id),
    user: dict = Depends(current_user),
):
    """清除指定来源的文档（向量 + 原文件 + 对应 chunk 产物）。"""
    document_service.clear_sources(user["username"], body.sources, session_id=session_id)
    return views.chosen_cleared()


@router.post("/upload")
async def upload_file(
    files: List[UploadFile] = File(...),
    session_id: str = Depends(session_id_required),
    user: dict = Depends(current_user),
):
    """上传文件到当前用户的暂存目录（仅 PDF，不解析）。

    Raises:
        HTTPException 400: 缺少 session_id（依赖注入校验）。
        AppError 400: 文件名非法或非 PDF。
    """
    pairs = [(file.filename, await file.read(), file.content_type) for file in files]
    saved = document_service.save_uploads(user["username"], pairs, session_id=session_id)
    return views.upload_result(saved)


@router.post("/upload_embeddings")
async def upload_embeddings(
    files: List[UploadFile] = File(...),
    session_id: str = Depends(session_id_required),
    user: dict = Depends(current_user),
    stream: bool = Query(False, description="是否 SSE 流式返回处理进度"),
):
    """上传文件并立即向量化入库到当前用户分区。

    Raises:
        HTTPException 400: 缺少 session_id（依赖注入校验）。
        AppError 400: 文件名非法或非 PDF。
        AppError 413: 存储空间不足。
    """
    files_data = [(file.filename, await file.read(), file.content_type) for file in files]
    role = user.get("role", "user")

    if stream:
        return views.sse_upload(_sse(document_service.iter_upload_progress(user["username"], session_id, files_data, role)))

    return views.upload_result(document_service.upload_and_index(user["username"], files_data, role=role, session_id=session_id))


@router.get("/documents/{username}")
async def get_documents(username: str, user: dict = Depends(current_user)):
    """获取当前用户分区下的文档列表（路径 username 仅用于路由兼容）。"""
    return views.list_(document_service.list_documents(user["username"]))


@router.get("/documents/storage/info")
async def get_storage_info(user: dict = Depends(current_user)):
    """获取当前用户的存储使用情况。"""
    return views.storage_info(storage_service.usage(user["username"], user.get("role", "user")))


@router.get("/documents/file/{filename:path}")
async def download_document(
    request: Request,
    filename: str,
    token: str = Query(None, description="JWT token（无法携带 Header 时用）"),
):
    """返回当前用户上传过的原文件（inline）。

    Raises:
        HTTPException 401: token 缺失/无效。
        AppError 403/404: 路径穿越 / 文件不存在。
    """
    payload = media_identity(request, token)
    path = document_service.resolve_user_file(payload.get("username", ""), filename)
    return views.inline_path(path)


@router.get("/documents/image/{doc_stem}/{img_name:path}")
async def serve_mineru_image(
    request: Request,
    doc_stem: str,
    img_name: str,
    token: str = Query(None),
):
    """提供 MinerU 解析产出的图片（逐级放宽匹配）。

    Raises:
        HTTPException 401: token 无效。
        AppError 404: 图片未找到。
    """
    media_identity(request, token)
    return views.inline_path(document_service.find_image(doc_stem, img_name))


@router.get("/documents/image/{img_name:path}")
async def serve_mineru_image_global(
    request: Request,
    img_name: str,
    token: str = Query(None),
):
    """全局搜索 MinerU 图片（仅有图片 hash、无 doc_stem 时使用）。

    Raises:
        HTTPException 401: token 无效。
        AppError 404: 图片未找到。
    """
    media_identity(request, token)
    return views.inline_path(document_service.find_image_global(img_name))
