"""modules.history.service —— 对话历史领域 CRUD（ORM 实体即领域模型）。

历史的条目结构、归档、覆盖写等**领域语义**在此实现；条目为 ``HistoryEntry`` 实体。
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from .entity import HistoryEntry


class HistoryService:
    """对话历史领域操作。"""

    def __init__(self, repo: object):
        """初始化。

        Args:
            repo: 通用仓储（collection="history"，返回 HistoryEntry 实体）。
        """
        self._repo = repo

    # ── 读取 ──

    def get_session_history(self, session_id: str) -> Optional[list]:
        """读取会话的活跃历史（归档不含）；无数据返回 None。"""
        entries = self._repo.find("history", {"session_id": session_id, "archived": 0}, order_by="id")
        if not entries:
            return None
        out = []
        for e in entries:
            entry: dict = {"id": e.id, "type": e.type, "timestamp": e.timestamp}
            if e.type == "qa":
                entry["user"] = e.user or ""
                entry["assistant"] = e.assistant or ""
            elif e.type == "turn":
                entry["messages"] = e.messages or []
            elif e.type == "event":
                entry["event_type"] = e.event_type or ""
                entry["files"] = e.files or []
            out.append(entry)
        return out

    # ── 写入 ──

    def insert_session_history(self, session_id: str, user: str, assistant: str) -> bool:
        return self._insert(session_id, type="qa", user=user, assistant=assistant)

    def insert_session_turn(self, session_id: str, messages: list) -> bool:
        return self._insert(session_id, type="turn", messages=messages)

    def insert_session_event(self, session_id: str, event_type: str, files: list) -> bool:
        return self._insert(session_id, type="event", event_type=event_type, files=list(files or []))

    def _insert(self, session_id: str, **fields) -> bool:
        if not session_id:
            return False
        entry = HistoryEntry(
            session_id=session_id,
            archived=0,
            timestamp=datetime.now().isoformat(),
            **fields,
        )
        return self._repo.insert("history", entry) is not None

    # ── 删除 / 归档 / 覆盖 ──

    def delete_session_history(self, session_id: str) -> bool:
        """删除会话的全部历史（含归档）。"""
        return self._repo.delete_where("history", {"session_id": session_id}) > 0

    def archive_history(self, session_id: str, messages: list = None) -> bool:
        """把活跃历史复制为 archived=1（活跃保留）；已归档过则跳过。"""
        active = self._repo.find("history", {"session_id": session_id, "archived": 0})
        if not active:
            return False
        if self._repo.count("history", {"session_id": session_id, "archived": 1}) > 0:
            return False
        for e in active:
            self._repo.insert("history", HistoryEntry(
                session_id=e.session_id,
                type=e.type,
                user=e.user,
                assistant=e.assistant,
                messages=e.messages,
                event_type=e.event_type,
                files=list(e.files or []),
                archived=1,
                timestamp=e.timestamp,
            ))
        return True

    def replace_session_history(self, session_id: str, history: list) -> bool:
        """整体覆盖会话的活跃历史（先删活跃，再逐条写入）。"""
        self._repo.delete_where("history", {"session_id": session_id, "archived": 0})
        for item in history or []:
            entry = HistoryEntry(
                session_id=session_id,
                type=item.get("type", "qa"),
                user=item.get("user"),
                assistant=item.get("assistant"),
                messages=item.get("messages"),
                event_type=item.get("event_type"),
                files=item.get("files") or [],
                archived=0,
                timestamp=item.get("timestamp") or datetime.now().isoformat(),
            )
            self._repo.insert("history", entry)
        return True