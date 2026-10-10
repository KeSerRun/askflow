"""agent.checkpoint —— 图运行快照持久化，支持断点续跑。

语义：
  - 每个超步（agent / tools 节点结束后）把该线程（session）的图状态存为 JSON 快照；
  - 一次生成**正常完成**后清除快照；
  - 中断 / 崩溃 / 达限时快照保留，供 ``resume`` 续跑（可加预算）。

存储走统一 SQLAlchemy 仓储（SQLite / MySQL 通用），建表由 create_all 完成。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime

from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import mapped_column

from infra.adapters.storage import Base


class GraphCheckpoint(Base):
    """线程级图状态快照（每 thread 保存最新一条）。"""

    __tablename__ = "graph_checkpoints"

    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    thread_id = mapped_column(String(255), nullable=False, index=True)
    checkpoint_id = mapped_column(String(64), nullable=False)
    state = mapped_column(Text, nullable=False)   # JSON
    meta = mapped_column(Text, nullable=False)    # JSON
    updated_at = mapped_column(String(40), nullable=False)


class CheckpointStore:
    """图快照存储：save / load / clear（按 thread_id）。"""

    COLLECTION = "graph_checkpoints"

    def __init__(self, repo: object):
        """初始化。

        Args:
            repo: 通用仓储（collection="graph_checkpoints"，返回 GraphCheckpoint 实体）。
        """
        self._repo = repo

    def save(self, thread_id: str, state: dict, meta: dict | None = None) -> None:
        """保存最近快照（存在则覆盖）。"""
        doc = json.dumps(state, ensure_ascii=False)
        meta_json = json.dumps(meta or {}, ensure_ascii=False)
        now = datetime.now().isoformat(timespec="seconds")
        rows = self._repo.find(self.COLLECTION, {"thread_id": thread_id})
        if rows:
            self._repo.update_where(
                self.COLLECTION,
                {"thread_id": thread_id},
                {
                    "checkpoint_id": uuid.uuid4().hex,
                    "state": doc,
                    "meta": meta_json,
                    "updated_at": now,
                },
            )
        else:
            self._repo.insert(
                self.COLLECTION,
                GraphCheckpoint(
                    thread_id=thread_id,
                    checkpoint_id=uuid.uuid4().hex,
                    state=doc,
                    meta=meta_json,
                    updated_at=now,
                ),
            )

    def load(self, thread_id: str) -> dict | None:
        """读取最近快照状态；无快照或解析失败返回 None。"""
        rows = self._repo.find(self.COLLECTION, {"thread_id": thread_id})
        if not rows:
            return None
        try:
            return json.loads(rows[0].state)
        except (ValueError, AttributeError):
            return None

    def clear(self, thread_id: str) -> None:
        """删除该线程快照（正常完成时调用）。"""
        try:
            self._repo.delete_where(self.COLLECTION, {"thread_id": thread_id})
        except Exception:
            pass
