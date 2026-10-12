"""健康检查接口：返回各外部依赖的完整状态（Controller）。"""

from fastapi import APIRouter

from core.deps import health_service

from . import vo as views

router = APIRouter(prefix="/api/health", tags=["health"])


@router.get("")
def heartbeat():
    """心跳：进程存活即 200（不依赖任何外部服务）。"""
    return views.heartbeat()


@router.get("/check")
def health_check():
    """完整依赖健康检查（Chat / Embedding / MinerU / SearXNG / Milvus / MinIO）。

    Returns:
        JSONResponse: ``{"status": ..., "checks": {...}}``。
    """
    return views.report(health_service.run())