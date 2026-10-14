"""modules.session.service —— 会话/历史用例（创建 / 列出 / 删除 / 读取）。

基于通用仓储（collection="sessions"，ORM 实体即领域模型）+ ``HistoryService``：
  - 会话列出与**首条消息预览**（派生字段，不属于持久化）
  - 会话**归属校验**（禁止操作他人会话）
"""

from __future__ import annotations

from datetime import datetime

from core.app_errors import Conflict, SessionAccessDenied  # noqa: F401
from core.pagination import paginate_query

from .entity import Session


class SessionService:
    """会话与历史的用例编排。"""

    def __init__(self, repo: object, history: object, *,
                 preview_chars: int = 40, cleanup: callable | None = None):
        """初始化。

        Args:
            repo: 通用仓储（collection="sessions"，返回 Session 实体）。
            history: HistoryService（读取/删除会话历史）。
            preview_chars: 会话预览截断字符数。
            cleanup: 可选回调 ``cleanup(user_id, session_id)``，删除会话时清理对象存储
                （会话附件 / query_img 等，随 ``sessions/{user_id}/{session_id}/`` 前缀一并删除）。
        """
        self._repo = repo
        self._history = history
        self._preview_chars = preview_chars
        self._cleanup = cleanup

    def _run_cleanup(self, user_id, session_id) -> None:
        if callable(self._cleanup) and user_id is not None and session_id:
            try:
                self._cleanup(user_id, session_id)
            except Exception:  # noqa: BLE001
                pass

    # ── 创建 / 列出 ──

    def create(self, session_id: str, username: str, user_id: int | None = None) -> None:
        """创建会话（归属 user_id，username 冗余快照供展示）。

        Raises:
            AppError 409: 会话已存在。
        """
        if self._repo.find("sessions", {"session_id": session_id}):
            raise Conflict("Failed to create session")
        self._repo.insert("sessions", Session(
            session_id=session_id,
            username=username,
            user_id=user_id,
            created_at=datetime.now().isoformat(),
        ))

    def list_sessions(self, user_id: int | None) -> list[dict]:
        """列出某用户（user_id）的会话（含首条消息预览）。"""
        sessions = self._repo.find("sessions", {"user_id": user_id}, order_by="id")
        result = []
        for session in sessions:
            result.append({
                "id": session.session_id,
                "created_at": session.created_at,
                "first_msg": self._preview(self._history.get_session_history(session.session_id) or []),
            })
        return result

    # ── 归属 ──

    def owned_ids(self, user_id: int | None) -> list[str]:
        """返回该用户（user_id）名下的会话 ID 列表。"""
        return [s.session_id for s in self._repo.find("sessions", {"user_id": user_id})]

    def _assert_owned(self, session_id: str, user_id: int | None) -> None:
        if session_id not in self.owned_ids(user_id):
            raise SessionAccessDenied(session_id)

    # ── 删除 ──

    def delete(self, session_id: str, user_id: int | None) -> None:
        """删除会话及其历史（仅限本人），并清理对象存储（含 query_img）。

        Raises:
            SessionAccessDenied: 会话不属于该用户。
        """
        self._assert_owned(session_id, user_id)
        self._repo.delete_where("sessions", {"session_id": session_id})
        self._history.delete_session_history(session_id)
        self._run_cleanup(user_id, session_id)

    # ── 历史 ──

    def get_history(self, session_id: str, user_id: int | None) -> list | None:
        """读取会话历史（仅限本人）。"""
        self._assert_owned(session_id, user_id)
        return self._history.get_session_history(session_id)

    def clear_history(self, session_id: str, user_id: int | None) -> None:
        """清除会话历史（仅限本人）。"""
        self._assert_owned(session_id, user_id)
        self._history.delete_session_history(session_id)

    # ── 管理（管理员：全部用户，跳过归属校验） ──

    def list_all(self, *, page: int = 1, page_size: int = 20,
                 username: str | None = None, keyword: str | None = None) -> dict:
        """分页列出全部会话（可过滤用户名 / 关键词），附历史条数与首条预览。

        分页下推仓储层；仅对当前页会话查历史（避免对全表做 N+1）。
        """
        where: dict = {}
        if username:
            where["username"] = username
        if keyword:
            where["__or__"] = [
                {"session_id__icontains": keyword},
                {"username__icontains": keyword},
            ]

        def _row(s) -> dict:
            history = self._history.get_session_history(s.session_id) or []
            return {
                "session_id": s.session_id,
                "user_id": getattr(s, "user_id", None),
                "username": s.username,
                "created_at": s.created_at,
                "history_count": len(history),
                "first_msg": self._preview(history),
            }

        return paginate_query(
            self._repo, "sessions", where=where or None, order_by="-id",
            page=page, page_size=page_size, key="items", serialize=_row,
        )

    def admin_get_history(self, session_id: str) -> list | None:
        """管理员读取任意会话的历史。"""
        return self._history.get_session_history(session_id)

    def admin_clear_history(self, session_id: str) -> None:
        """管理员清空任意会话的历史（保留会话本身）。"""
        self._history.delete_session_history(session_id)

    def admin_delete(self, session_id: str) -> None:
        """管理员删除任意会话及其历史，并清理对象存储（含 query_img）。"""
        rec = self._repo.find("sessions", {"session_id": session_id})
        user_id = getattr(rec[0], "user_id", None) if rec else None
        self._repo.delete_where("sessions", {"session_id": session_id})
        self._history.delete_session_history(session_id)
        self._run_cleanup(user_id, session_id)

    # ── 内部 ──

    def _preview(self, history: list) -> str:
        """从历史首条推导会话预览（用户消息前 N 字符，剥离附带图片说明块，标题只取真实消息文本）。"""
        if not history:
            return ""
        first = history[0]
        content = ""
        if first.get("type") == "turn":
            for m in first.get("messages", []) or []:
                if m.get("role") == "user" and m.get("content"):
                    content = str(m["content"])
                    break
        else:
            content = str(first.get("user", ""))
        # 标题 = 消息正文；去掉后端注入的「用户附带了图片：[...]」说明块
        idx = content.find("\n\n[用户附带了图片")
        if idx != -1:
            content = content[:idx].rstrip()
        return content[: self._preview_chars]
