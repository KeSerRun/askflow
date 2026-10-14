"""modules.common —— 视图层公共构件（响应/事件流格式化）。

视图层只负责"把数据变成 HTTP 响应"，不含业务逻辑、不访问存储。
"""

from __future__ import annotations

import json as _json
import mimetypes
import os
from urllib.parse import quote

from fastapi.responses import JSONResponse, Response


def json(content, status_code: int = 200) -> JSONResponse:
    """构造 JSON 响应。"""
    return JSONResponse(content=content, status_code=status_code)


def message(text: str, status_code: int = 200, **extra) -> JSONResponse:
    """构造 ``{"message": text, ...}`` 响应。"""
    return JSONResponse(content={"message": text, **extra}, status_code=status_code)


def sse_event(data: dict) -> str:
    """把 dict 序列化为一条 SSE ``data:`` 行（``text/event-stream``）。"""
    return f"data: {_json.dumps(data, ensure_ascii=False)}\n\n"


def content_disposition(filename: str, *, inline: bool = True) -> str:
    """构造 ``Content-Disposition``（RFC 5987，兼容非 ASCII 文件名）。

    HTTP 头只能是 latin-1；中文名直接写入会抛 ``UnicodeEncodeError`` 致响应 500。
    这里给 ASCII 回退名 + ``filename*=UTF-8''<百分号编码>``。
    """
    name = (filename or "").strip() or "file"
    ascii_fallback = name.encode("ascii", "ignore").decode("ascii").strip()
    if not ascii_fallback or ascii_fallback.startswith("."):
        ext = os.path.splitext(name)[1]
        ascii_fallback = f"file{ext}" if ext else "file"
    ascii_fallback = ascii_fallback.replace('"', "").replace("\\", "")
    kind = "inline" if inline else "attachment"
    return f"{kind}; filename=\"{ascii_fallback}\"; filename*=UTF-8''{quote(name, safe='')}"


def file_response(data: bytes, filename: str, media_type: str | None = None, *, inline: bool = True) -> Response:
    """返回文件字节（默认 inline；Content-Disposition 兼容中文名）。"""
    mt = media_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"
    return Response(
        content=data, media_type=mt, headers={"Content-Disposition": content_disposition(filename, inline=inline)}
    )
