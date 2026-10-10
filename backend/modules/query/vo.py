"""modules.query —— 问答响应组装（含 SSE 事件流）。"""

from __future__ import annotations

from fastapi.responses import JSONResponse, StreamingResponse

from core.responses import json, sse_event


def answer(answer: str) -> JSONResponse:
    """非流式答案响应。"""
    return json({"answer": answer})


def cancel_ack() -> JSONResponse:
    """中断信号确认响应。"""
    return json({"message": "已发送中断信号"})


def styles(styles: list) -> JSONResponse:
    """回答风格列表响应。"""
    return json({"styles": styles})


def workflows(workflows: list) -> JSONResponse:
    """工作流列表响应。"""
    return json({"workflows": workflows})


def sse(generator) -> StreamingResponse:
    """把 dict 生成器包装为 SSE ``text/event-stream`` 响应。"""
    def _wrap():
        for item in generator:
            yield sse_event(item)
    return StreamingResponse(_wrap(), media_type="text/event-stream")
