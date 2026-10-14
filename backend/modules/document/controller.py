"""文档接口（Controller）：

- **会话附件暂存**（对话页）：上传 / 列出 / 下载 / 删除，按 ``session_id`` 隔离，
  只暂存（MinIO）、**不解析不入向量库**（解析产物为 txt 供会话内工具检索）；
- **图片直链**：答案中引用的 MinerU 图片（``/images/...`` 与 ``/documents/image/...``）。

业务（文件名校验 / 对象存储读写 / 图片解析）全部在 ``modules.DocumentService``；
系统文档的 MinerU 解析 + 向量化由管理端 ``/api/admin/database/upload`` 触发。
"""

import re as _re

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile

from core.concurrency import to_thread
from core.deps import (
    document_service,
    history_service,
    require_auth,
    require_media_auth,
    require_session_id,
)

from . import vo as views

router = APIRouter(prefix="/api", tags=["documents"])


# ── 媒体直链（LLM 输出的 /images/{hash}.jpg） ──

media_router = APIRouter(prefix="/images", tags=["media"])


@media_router.get("/{img_name:path}")
def serve_root_image(request: Request, img_name: str, token: str = Query(None)):
    """搜索并返回图片。处理 LLM 输出的 /images/hash.jpg 格式。

    Raises:
        HTTPException 401: token 缺失或无效（require_media_auth）。
        HTTPException 404: 图片未找到。
    """
    require_media_auth(request, token)
    found = views.inline_bytes_global(document_service, img_name)
    if found is None:
        raise HTTPException(status_code=404, detail="image not found")
    return found


# ── 会话附件暂存（对话页上传，仅落盘） ──

@router.post("/session_files/upload")
async def upload_session_files(
    files: list[UploadFile] = File(...),
    session_id: str = Depends(require_session_id),
    user: dict = Depends(require_auth),
):
    """上传附件到当前会话暂存目录（只落盘、不入向量库），随后后台 MinerU 解析为 txt。

    Raises:
        HTTPException 400: 缺少 session_id。
        AppError 413: 会话附件总大小超过上限。
        AppError 400: 文件名非法。
    """
    pairs = [(file.filename, await file.read(), file.content_type) for file in files]
    saved = await to_thread(
        document_service.save_session_files, user["user_id"], session_id, pairs
    )
    names = [s["filename"] for s in saved]
    document_service.schedule_session_parse(user["user_id"], session_id, names)
    # 记录上传事件：聊天列表可见 + 注入 LLM 上下文（<operation：upload files: ...>）
    if names:
        await to_thread(history_service.insert_session_event, session_id, "upload", names)
    return views.session_files(
        saved,
        document_service.session_usage(user["user_id"], session_id),
    )


@router.get("/session_files/parse_status")
def session_parse_status(
    session_id: str = Depends(require_session_id),
    user: dict = Depends(require_auth),
):
    """返回当前会话各附件的 MinerU 解析状态（pending/parsing/success/failed/skipped）。"""
    return views.session_files_parse(
        document_service.session_parse_status(user["user_id"], session_id)
    )


@router.get("/session_files")
def list_session_files(
    session_id: str = Depends(require_session_id),
    user: dict = Depends(require_auth),
):
    """列出当前会话暂存文件与用量。"""
    files = document_service.list_session_files(user["user_id"], session_id)
    return views.session_files(files, document_service.session_usage(user["user_id"], session_id))


@router.delete("/session_files/{filename:path}")
def delete_session_file(
    filename: str,
    session_id: str = Depends(require_session_id),
    user: dict = Depends(require_auth),
):
    """删除当前会话里的某个附件。"""
    document_service.delete_session_file(user["user_id"], session_id, filename)
    history_service.insert_session_event(session_id, "delete", [filename])
    return views.session_file_deleted(filename)


@router.delete("/session_files")
def clear_session_files(
    session_id: str = Depends(require_session_id),
    user: dict = Depends(require_auth),
):
    """清空当前会话的全部附件。"""
    names = [f["name"] for f in document_service.list_session_files(user["user_id"], session_id)]
    document_service.clear_session_files(user["user_id"], session_id)
    if names:
        history_service.insert_session_event(session_id, "delete_all", names)
    return views.session_files_cleared()


@router.get("/session_files/file/{filename:path}")
def download_session_file(
    filename: str,
    session_id: str = Depends(require_session_id),
    user: dict = Depends(require_auth),
):
    """下载 / 预览会话暂存的原文件（inline，从对象存储读取）。

    Raises:
        AppError 403/404: 路径穿越 / 文件不存在。
    """
    data, name = document_service.read_session_file(user["user_id"], session_id, filename)
    return views.inline_bytes(data, name)


# ── 图片直链（按 doc_stem / 全局搜索；从对象存储读取） ──

@router.get("/documents/query_image")
def serve_query_image(
    request: Request,
    key: str = Query(...),
    token: str = Query(None),
):
    """提供对话页粘贴图片（``sessions/{user_id}/{session_id}/query_img/...``）；仅属主或管理员可读。

    Raises:
        HTTPException 400: key 非法。
        HTTPException 401: token 无效。
        HTTPException 403: 非本人/非管理员。
        HTTPException 404: 图片不存在。
    """
    payload = require_media_auth(request, token)
    m = _re.match(r"^sessions/(\d+)/", str(key or "").lstrip("/"))
    if not m:
        raise HTTPException(status_code=400, detail="非法图片键")
    owner = int(payload.get("user_id") or 0)
    if owner != int(m.group(1)) and payload.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Forbidden")
    found = document_service.read_query_image(key)
    if found is None:
        raise HTTPException(status_code=404, detail="image not found")
    data, _media_type, name = found
    return views.inline_bytes(data, name)


@router.get("/documents/chunk_image")
def serve_chunk_image(
    request: Request,
    key: str = Query(...),
    token: str = Query(None),
):
    """提供 MinerU 解析图片（会话附件或知识库 ``chunk_out/.../images/``）；仅属主或管理员可读会话图。

    Raises:
        HTTPException 400: key 非法。
        HTTPException 401: token 无效。
        HTTPException 403: 非本人/非管理员。
        HTTPException 404: 图片不存在。
    """
    payload = require_media_auth(request, token)
    key = str(key or "").lstrip("/")
    m = _re.match(r"^sessions/(\d+)/", key)
    if m:
        owner = int(payload.get("user_id") or 0)
        if owner != int(m.group(1)) and payload.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Forbidden")
    elif not key.startswith("uploads/"):
        raise HTTPException(status_code=400, detail="非法图片键")
    found = document_service.read_chunk_image(key)
    if found is None:
        raise HTTPException(status_code=404, detail="image not found")
    data, _media_type, name = found
    return views.inline_bytes(data, name)


@router.get("/documents/image/{doc_stem}/{img_name:path}")
def serve_mineru_image(
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
    require_media_auth(request, token)
    return views.mineru_image(document_service, doc_stem, img_name)


@router.get("/documents/image/{img_name:path}")
def serve_mineru_image_global(
    request: Request,
    img_name: str,
    token: str = Query(None),
):
    """全局搜索 MinerU 图片（仅有图片 hash、无 doc_stem 时使用）。

    Raises:
        HTTPException 401: token 无效。
        AppError 404: 图片未找到。
    """
    require_media_auth(request, token)
    return views.inline_bytes_global(document_service, img_name)
