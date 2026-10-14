"""modules.deliverable.vo —— 交付物响应组装。"""

from __future__ import annotations

from fastapi.responses import JSONResponse, Response

from core.responses import file_response, json


def templates(items: list) -> JSONResponse:
    return json({"templates": items})


def template(data: dict) -> JSONResponse:
    return json(data)


def ok(data: dict) -> JSONResponse:
    return json(data)


def deliverables(items: list) -> JSONResponse:
    return json({"deliverables": items})


def pdf(data: bytes, filename: str) -> Response:
    """返回 PDF（inline，浏览器可直接预览/下载）。"""
    return file_response(data, filename, "application/pdf", inline=True)
