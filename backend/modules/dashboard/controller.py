"""管理后台 API - 仪表盘（Controller）"""

from fastapi import APIRouter, Depends

from core import runtime
from core.deps import dashboard_service, require_admin
from agent.tools import registry as tool_registry
from . import vo as views

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/dashboard")
async def get_dashboard(user: dict = Depends(require_admin)):
    """系统总览：领域统计（DashboardService）+ 运行时统计（请求/工具）。"""
    return views.overview(
        dashboard_service.overview(),
        request_stats=runtime.request_stats,
        tool_call_counts=tool_registry.call_counts,
    )
