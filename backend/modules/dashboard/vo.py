"""modules.admin.dashboard —— 仪表盘响应组装。"""

from __future__ import annotations

import time

from fastapi.responses import JSONResponse

from core.responses import json


def overview(domain: dict, request_stats=None, tool_call_counts=None) -> JSONResponse:
    """合并领域统计 + 运行时统计（请求/工具）为总览响应。"""
    payload = dict(domain)
    payload["request_stats"] = _request_stats(request_stats)
    payload["tool_call_counts"] = dict(tool_call_counts or {})
    return json(payload)


def ok(payload: dict) -> JSONResponse:
    """通用 JSON 响应。"""
    return json(payload)


def _request_stats(rs) -> dict:
    """接收 RequestLogService.stats() 的 dict；缺省返回空统计。"""
    if not rs:
        return {
            "total_requests": 0, "total_errors": 0,
            "by_method": {}, "start_time": time.time(), "uptime_seconds": 0,
        }
    return dict(rs)
