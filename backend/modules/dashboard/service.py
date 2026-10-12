"""modules.dashboard.service —— 仪表盘统计用例（计数类 + 服务器资源）。

聚合用户数 / 管理员 / 会话数 / 向量库分布等**计数**统计；
``server_resources`` 读取**服务器 CPU / RAM 使用情况**（psutil，不可用时降级不可用）。
请求统计等运行时数据由控制器补充；
HTTP 调用记录（写入 + 聚合）位于 ``modules.logger.service.RequestLogService``。
"""

from __future__ import annotations

import os
from datetime import datetime


class DashboardService:
    """系统总览统计（计数类）。"""

    def __init__(self, user_service: object, vector_store: object, repo: object = None):
        """初始化。

        Args:
            user_service: UserService（用户统计）。
            vector_store: 向量库（文档/切块分布）。
            repo: 通用仓储（会话总数统计）。
        """
        self._users = user_service
        self._vector = vector_store
        self._repo = repo

    def overview(self) -> dict:
        """返回领域统计（不含请求统计/工具计数/服务器资源）。"""
        users_data = self._users.get_all_users(page=1, page_size=999999)
        users_list = users_data.get("items", [])
        user_count = users_data.get("total", 0)
        admin_count = sum(1 for u in users_list if u.get("role") == "admin")

        vs = self._vector
        metadata = (vs.metadata if vs and vs.metadata else []) or []
        total_chunks = len(metadata)

        sources = set(m.get("source", "") for m in metadata if m.get("source"))

        return {
            "healthy": True,
            "user_count": user_count,
            "admin_count": admin_count,
            "session_count": self._repo.count("sessions") if self._repo else 0,
            "document_count": len(sources),
            "chunk_count": total_chunks,
            "embedding_dim": vs.dimension if vs else None,
            "embedding_model": getattr(vs, "embedding_model", None) if vs else None,
        }

    def server_resources(self) -> dict:
        """服务器资源使用情况（CPU / RAM）。

        Returns:
            ``{"available": False, "reason": ...}`` 或
            ``{"available": True, "status", "warnings", "cpu", "memory", "sampled_at"}``：
            cpu 含 percent / cores，memory 含 percent / used / total（字节）。
        """
        try:
            import psutil
        except ImportError:
            return {"available": False, "reason": "psutil 未安装（pip install psutil）"}

        try:
            cpu_pct = float(psutil.cpu_percent(interval=0.3))
            vm = psutil.virtual_memory()
            cores = os.cpu_count() or 0

            status = "healthy"
            warnings: list[str] = []
            if cpu_pct > 90:
                warnings.append("CPU 使用率过高（>90%）")
                status = "warning"
            if vm.percent > 90:
                warnings.append("内存使用率过高（>90%）")
                status = "warning"

            return {
                "available": True,
                "status": status,
                "warnings": warnings,
                "cpu": {"percent": round(cpu_pct, 1), "cores": cores},
                "memory": {
                    "percent": round(float(vm.percent), 1),
                    "used": int(vm.used),
                    "total": int(vm.total),
                },
                "sampled_at": datetime.now().isoformat(timespec="seconds"),
            }
        except Exception as e:  # noqa: BLE001
            return {"available": False, "reason": f"获取系统资源失败: {e}"}