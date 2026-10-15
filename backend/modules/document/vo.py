"""modules.documents —— 文档响应组装（会话附件 + 文件/图片下载，均从对象存储取字节）。"""

from __future__ import annotations

from fastapi import HTTPException
from fastapi.responses import JSONResponse, Response

from core.responses import file_response, json, message


def session_files(files: list, usage: dict) -> JSONResponse:
    """会话附件列表 / 上传结果（含用量）。"""
    return json({"files": files, "usage": usage})


def session_files_parse(data: dict) -> JSONResponse:
    """会话附件 MinerU 解析状态（files 为 {文件名: {status, error}}）。"""
    return json({"files": data.get("files", {}), "usage": data.get("usage", {})})


def session_file_deleted(filename: str) -> JSONResponse:
    return message(f"附件 {filename} 已删除")


def session_files_cleared() -> JSONResponse:
    return message("会话附件已清空")


def inline_bytes(data: bytes, filename: str) -> Response:
    """以 inline 方式返回字节（PDF/图片可在浏览器直接打开）。"""
    return file_response(data, filename, inline=True)


def mineru_image(document_service, doc_stem: str, img_name: str,
                 partition: str | None = None) -> Response:
    """按 doc_stem 从对象存储返回 MinerU 图片；未找到抛 404。"""
    found = document_service.read_image(doc_stem, img_name, partition)
    if found is None:
        raise HTTPException(status_code=404, detail="image not found")
    data, media_type, _name = found
    return Response(content=data, media_type=media_type)


def inline_bytes_global(document_service, img_name: str) -> Response | None:
    """全局从对象存储返回图片；未找到返回 None（由调用方抛 404）。"""
    found = document_service.read_image_global(img_name)
    if found is None:
        return None
    data, media_type, _name = found
    return Response(content=data, media_type=media_type)
