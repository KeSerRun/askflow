"""modules.common —— 视图层公共构件（响应/事件流格式化）。

视图层只负责"把数据变成 HTTP 响应"，不含业务逻辑、不访问存储。
"""

from __future__ import annotations

import json as _json

from fastapi.responses import JSONResponse


def json(content, status_code: int = 200) -> JSONResponse:
    """构造 JSON 响应。"""
    return JSONResponse(content=content, status_code=status_code)


def message(text: str, status_code: int = 200, **extra) -> JSONResponse:
    """构造 ``{"message": text, ...}`` 响应。"""
    return JSONResponse(content={"message": text, **extra}, status_code=status_code)


def sse_event(data: dict) -> str:
    """把 dict 序列化为一条 SSE ``data:`` 行（``text/event-stream``）。"""
    return f"data: {_json.dumps(data, ensure_ascii=False)}\n\n"
