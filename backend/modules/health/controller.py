"""健康检查接口：返回各外部依赖的完整状态（Controller）。"""

import asyncio

from fastapi import APIRouter

from infra.health import run_all

from core.deps import system
from . import vo as views

router = APIRouter(prefix="/api/health", tags=["health"])


@router.get("")
async def heartbeat():
    """心跳：进程存活即 200（不依赖任何外部服务）。"""
    return views.heartbeat()


@router.get("/check")
async def health_check():
    """完整依赖健康检查（Chat / Embedding / MinerU / 向量库）。

    Returns:
        JSONResponse: ``{"status": ..., "checks": {...}}``。
    """
    loop = asyncio.get_running_loop()

    def _sync():
        return run_all(
            chat_client=system.chat_client,
            embed_client=system.embed_client,
            vector_store=system.vector_store,
        )

    result = await loop.run_in_executor(None, _sync)
    return views.report(result)