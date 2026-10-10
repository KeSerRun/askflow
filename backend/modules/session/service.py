"""modules.session.service —— 会话/历史用例（创建 / 列出 / 删除 / 读取）。

基于通用仓储（collection="sessions"，ORM 实体即领域模型）+ ``HistoryService``：
  - 会话列出与**首条消息预览**（派生字段，不属于持久化）
  - 会话**归属校验**（禁止操作他人会话）
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from core.errors import Conflict, SessionAccessDenied  # noqa: F401
from .entity import Session


class SessionService:
    """会话与历史的用例编排。"""

    def __init__(self, repo: object, history: object, *, preview_chars: int = 40):
        """初始化。

        Args:
            repo: 通用仓储（collection="sessions"，返回 Session 实体）。
            history: HistoryService（读取/删除会话历史）。
            preview_chars: 会话预览截断字符数。
        """
        self._repo = repo
        self._history = history
        self._preview_chars = preview_chars

    # ── 创建 / 列出 ──

    def create(self, session_id: str, username: str) -> None:
        """创建会话。

        Raises:
            AppError 409: 会话已存在。
        """
        if self._repo.find("sessions", {"session_id": session_id}):
            raise Conflict("Failed to create session")
        self._repo.insert("sessions", Session(
            session_id=session_id,
            username=username.lower(),
            created_at=datetime.now().isoformat(),
        ))

    def list_sessions(self, username: str) -> list[dict]:
        """列出用户会话（含首条消息预览）。"""
        sessions = self._repo.find("sessions", {"username": username.lower()}, order_by="id")
        result = []
        for session in sessions:
            result.append({
                "id": session.session_id,
                "created_at": session.created_at,
                "first_msg": self._preview(self._history.get_session_history(session.session_id) or []),
            })
        return result

    # ── 归属 ──

    def owned_ids(self, username: str) -> list[str]:
        """返回该用户名下的会话 ID 列表。"""
        return [s.session_id for s in self._repo.find("sessions", {"username": username.lower()})]

    def _assert_owned(self, session_id: str, username: str) -> None:
        if session_id not in self.owned_ids(username):
            raise SessionAccessDenied(session_id)

    # ── 删除 ──

    def delete(self, session_id: str, username: str) -> None:
        """删除会话及其历史（仅限本人）。

        Raises:
            SessionAccessDenied: 会话不属于该用户。
        """
        self._assert_owned(session_id, username)
        self._repo.delete_where("sessions", {"session_id": session_id})
        self._history.delete_session_history(session_id)

    # ── 历史 ──

    def get_history(self, session_id: str, username: str) -> Optional[list]:
        """读取会话历史（仅限本人）。"""
        self._assert_owned(session_id, username)
        return self._history.get_session_history(session_id)

    def clear_history(self, session_id: str, username: str) -> None:
        """清除会话历史（仅限本人）。"""
        self._assert_owned(session_id, username)
        self._history.delete_session_history(session_id)

    # ── 内部 ──

    def _preview(self, history: list) -> str:
        """从历史首条推导会话预览（用户消息前 N 字符）。"""
        if not history:
            return ""
        first = history[0]
        if first.get("type") == "turn":
            for m in first.get("messages", []) or []:
                if m.get("role") == "user" and m.get("content"):
                    return str(m["content"])[: self._preview_chars]
            return ""
        return str(first.get("user", ""))[: self._preview_chars]