"""modules.documents —— 文档响应组装（含文件/图片下载与 SSE）。"""

from __future__ import annotations

import mimetypes
import os

from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from core.responses import json, message


def added() -> JSONResponse:
    return message("Documents added successfully")


def cleared() -> JSONResponse:
    return message("User documents cleared successfully")


def chosen_cleared() -> JSONResponse:
    return message("Selected documents cleared successfully")


def upload_result(files: list) -> JSONResponse:
    return json({"files": files})


def list_(documents) -> JSONResponse:
    return json({"documents": documents})


def storage_info(payload: dict) -> JSONResponse:
    return json(payload)


def inline_file(path: str, media_type: str, filename: str) -> FileResponse:
    """以 inline 方式返回文件（PDF/图片可在浏览器直接打开）。"""
    return FileResponse(
        path=path,
        media_type=media_type,
        filename=filename,
        content_disposition_type="inline",
    )


def inline_path(path: str) -> FileResponse:
    """按扩展名推断媒体类型后以 inline 返回。"""
    media_type = mimetypes.guess_type(path)[0] or "application/octet-stream"
    return inline_file(path, media_type, os.path.basename(path))


def sse_upload(generator) -> StreamingResponse:
    """上传处理进度的 SSE 流响应。"""
    return StreamingResponse(generator, media_type="text/event-stream")