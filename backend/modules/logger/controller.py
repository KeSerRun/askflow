"""管理后台 API - 日志查看 Controller。

直接查询数据库日志表（不是读日志文件）：
- ``app_logs``    -> GET /api/admin/logs/app
- ``request_logs``（http 日志的数据库形态）-> GET /api/admin/logs/http
"""

from fastapi import APIRouter, Depends, HTTPException, Query

from core.deps import log_service, require_admin
from core.responses import json

router = APIRouter(prefix="/api/admin/logs", tags=["admin"])


@router.get("/app")
def app_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    level: str | None = Query(None),
    keyword: str | None = Query(None),
    user: dict = Depends(require_admin),
):
    """查询数据库中的应用日志（app_logs 表，按时间倒序）。"""
    return json(log_service.app_logs(page=page, page_size=page_size, level=level, keyword=keyword))


@router.delete("/app/{log_id}")
def delete_app_log(log_id: int, user: dict = Depends(require_admin)):
    """按 ID 删除一条应用日志。"""
    if not log_service.delete_app_log(log_id):
        raise HTTPException(status_code=404, detail=f"应用日志不存在: {log_id}")
    return json({"deleted": log_id})


@router.delete("/app")
def clear_app_logs(user: dict = Depends(require_admin)):
    """清空全部应用日志，返回删除条数。"""
    return json({"deleted": log_service.clear_app_logs()})


@router.get("/http")
def http_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    method: str | None = Query(None),
    username: str | None = Query(None),
    keyword: str | None = Query(None),
    user: dict = Depends(require_admin),
):
    """查询数据库中的 HTTP 调用记录（request_logs 表，按时间倒序）。"""
    return json(log_service.http_logs(page=page, page_size=page_size, method=method, username=username, keyword=keyword))


@router.delete("/http/{log_id}")
def delete_http_log(log_id: int, user: dict = Depends(require_admin)):
    """按 ID 删除一条 HTTP 调用记录。"""
    if not log_service.delete_http_log(log_id):
        raise HTTPException(status_code=404, detail=f"HTTP 日志不存在: {log_id}")
    return json({"deleted": log_id})


@router.delete("/http")
def clear_http_logs(user: dict = Depends(require_admin)):
    """清空全部 HTTP 调用记录，返回删除条数。"""
    return json({"deleted": log_service.clear_http_logs()})