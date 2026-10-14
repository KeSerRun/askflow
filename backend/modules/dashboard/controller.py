"""管理后台 API - 仪表盘（Controller）"""

from fastapi import APIRouter, Depends

from core.deps import dashboard_service, require_admin, request_stats, tool_service
from . import vo as views

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/dashboard")
def get_dashboard(user: dict = Depends(require_admin)):
    """系统总览：领域统计（DashboardService）+ 请求统计（缓存累加）+ 工具计数（agent_tools.call_count）。"""
    return views.overview(
        dashboard_service.overview(),
        request_stats=request_stats.snapshot(),
        tool_call_counts=tool_service.call_counts(),
    )


@router.get("/dashboard/resources")
def server_resources(user: dict = Depends(require_admin)):
    """服务器资源使用情况（CPU / RAM，psutil 采样）。"""
    return views.ok(dashboard_service.server_resources())
