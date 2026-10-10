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


def _request_stats(rs) -> dict:
    if not rs:
        return {
            "total_requests": 0, "total_errors": 0,
            "by_method": {}, "by_path": [],
            "start_time": time.time(), "uptime_seconds": 0,
        }
    return {
        "total_requests": rs.total_requests,
        "total_errors": rs.total_errors,
        "by_method": dict(rs.by_method),
        "start_time": rs.start_time,
        "uptime_seconds": int(time.time() - rs.start_time),
    }
