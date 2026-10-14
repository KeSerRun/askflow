"""modules.database.parent_store —— 正文父块内容存储（按 id 去重入库一次）。

向量库的每个正文子块只存 ``parent_id`` 引用；父块全文存本表，
避免在 Milvus 每行重复保存整段父块文本。
"""

from __future__ import annotations


class ChunkParentStore:
    """``chunk_parents`` 表读写（id=md5(父块全文)）。"""

    def __init__(self, repo: object):
        """初始化。

        Args:
            repo: 通用对象仓储（Sqlite/MySQL）。
        """
        self._repo = repo
        self._ensure()

    def _raw_engine(self):
        raw = getattr(self._repo, "_repo", self._repo)
        return raw._engine

    def _ensure(self) -> None:
        """确保表存在（幂等）。"""
        try:
            from infra.adapters.storage import Base
            Base.metadata.create_all(self._raw_engine(), checkfirst=True)
        except Exception:  # noqa: BLE001
            pass

    def save_parent(self, parent_id: str, text: str) -> None:
        """按 parent_id 去重保存父块内容（已存在则跳过）。"""
        pid = (parent_id or "").strip()
        txt = (text or "").strip()
        if not pid or not txt:
            return
        from sqlalchemy import text as _sa_text
        try:
            with self._raw_engine().begin() as conn:
                found = conn.execute(
                    _sa_text("SELECT 1 FROM chunk_parents WHERE id = :id"), {"id": pid},
                ).fetchone()
                if not found:
                    conn.execute(
                        _sa_text("INSERT INTO chunk_parents (id, text) VALUES (:id, :text)"),
                        {"id": pid, "text": txt},
                    )
        except Exception:  # noqa: BLE001 并发去重等
            pass

    def get_parent(self, parent_id: str):
        """按 parent_id 返回父块全文；不存在返回 None。"""
        pid = (parent_id or "").strip()
        if not pid:
            return None
        from sqlalchemy import text as _sa_text
        try:
            with self._raw_engine().connect() as conn:
                rows = conn.execute(
                    _sa_text("SELECT text FROM chunk_parents WHERE id = :id"),
                    {"id": pid},
                ).fetchall()
        except Exception:  # noqa: BLE001
            return None
        return rows[0][0] if rows else None
