"""modules.dashboard_service —— 仪表盘统计用例。

聚合用户数与向量库分布（业务统计）；请求统计/工具计数等 Web/Agent 运行时数据
由控制器补充。
"""

from __future__ import annotations


class DashboardService:
    """系统总览统计。"""

    def __init__(self, user_service: object, vector_store: object):
        """初始化。

        Args:
            user_service: UserService（用户统计）。
            vector_store: 向量库（文档/切块分布）。
        """
        self._users = user_service
        self._vector = vector_store

    def overview(self) -> dict:
        """返回领域统计（不含请求统计/工具计数）。"""
        users_data = self._users.get_all_users(page=1, page_size=999999)
        users_list = users_data.get("items", [])
        user_count = users_data.get("total", 0)
        admin_count = sum(1 for u in users_list if u.get("role") == "admin")

        vs = self._vector
        metadata = (vs.metadata if vs and vs.metadata else []) or []
        total_chunks = len(metadata)

        sources = set(m.get("source", "") for m in metadata if m.get("source"))

        partitions: dict = {}
        for m in metadata:
            p = m.get("partition", "default")
            partitions.setdefault(p, {"chunks": 0, "sources": set()})
            partitions[p]["chunks"] += 1
            if m.get("source"):
                partitions[p]["sources"].add(m["source"])
        partitions_summary = {
            p: {"chunks": v["chunks"], "sources": len(v["sources"])}
            for p, v in partitions.items()
        }

        return {
            "healthy": True,
            "user_count": user_count,
            "admin_count": admin_count,
            "session_count": 0,
            "document_count": len(sources),
            "chunk_count": total_chunks,
            "partitions": partitions_summary,
            "embedding_dim": vs.dimension if vs else None,
            "embedding_model": getattr(vs, "embedding_model", None) if vs else None,
        }
