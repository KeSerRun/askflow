"""modules/logger/service.py —— 日志相关用例（**全部查数据库表**）。

- ``LogService``：
  - ``app_logs``    应用日志（APPLogger 的数据库镜像）；
  - ``request_logs`` HTTP 调用记录（http 日志的数据库形态）。
- ``RequestLogService``：HTTP 调用明细写入。
  （请求统计的累加/快照见 ``modules.logger.stats.RequestStats``，不在此处、不查表。）
"""

from __future__ import annotations

from datetime import datetime

from core.pagination import paginate_query

from .entity import RequestLog


class LogService:
    """日志查询（数据库表 app_logs / request_logs）。"""

    def __init__(self, repo: object | None = None):
        """初始化。

        Args:
            repo: 通用仓储（查 app_logs / request_logs；为 None 则查询返回空）。
        """
        self._repo = repo

    def app_logs(self, *, page: int = 1, page_size: int = 50,
                 level: str | None = None, keyword: str | None = None) -> dict:
        """分页查询应用日志（app_logs 表，按 id 倒序；分页下推仓储层）。"""
        if not self._repo:
            return {"total": 0, "page": 1, "page_size": 0, "items": []}
        where: dict = {}
        if level:
            where["level"] = level.upper()
        if keyword:
            where["__or__"] = [
                {"message__icontains": keyword},
                {"module__icontains": keyword},
            ]
        return paginate_query(
            self._repo, "app_logs", where=where or None, order_by="-id",
            page=page, page_size=page_size, key="items", serialize=self._app_log_row,
        )

    def http_logs(self, *, page: int = 1, page_size: int = 50,
                  method: str | None = None, username: str | None = None,
                  keyword: str | None = None) -> dict:
        """分页查询 HTTP 调用记录（request_logs 表，按 id 倒序；分页下推仓储层）。"""
        if not self._repo:
            return {"total": 0, "page": 1, "page_size": 0, "items": []}
        where: dict = {}
        if method:
            where["method"] = method.upper()
        if username:
            where["username"] = username
        if keyword:
            where["path__icontains"] = keyword
        return paginate_query(
            self._repo, "request_logs", where=where or None, order_by="-id",
            page=page, page_size=page_size, key="items", serialize=self._http_log_row,
        )

    @staticmethod
    def _app_log_row(r) -> dict:
        return {
            "id": r.id,
            "created_at": r.created_at,
            "level": r.level,
            "logger": r.logger,
            "module": r.module,
            "lineno": r.lineno,
            "message": r.message,
        }

    # ── 删除 ──

    def delete_app_log(self, log_id) -> bool:
        """按 ID 删除一条应用日志，返回是否实际删除。"""
        if not self._repo:
            return False
        return bool(self._repo.delete("app_logs", log_id))

    def delete_http_log(self, log_id) -> bool:
        """按 ID 删除一条 HTTP 调用记录，返回是否实际删除。"""
        if not self._repo:
            return False
        return bool(self._repo.delete("request_logs", log_id))

    def clear_app_logs(self) -> int:
        """清空应用日志表，返回删除条数。"""
        if not self._repo:
            return 0
        return self._repo.delete_where("app_logs", {}) or 0

    def clear_http_logs(self) -> int:
        """清空 HTTP 调用记录表，返回删除条数。"""
        if not self._repo:
            return 0
        return self._repo.delete_where("request_logs", {}) or 0

    @staticmethod
    def _http_log_row(r) -> dict:
        return {
            "id": r.id,
            "created_at": r.created_at,
            "method": r.method,
            "path": r.path,
            "status_code": r.status_code,
            "is_error": r.is_error,
            "user_id": getattr(r, "user_id", None),
            "username": r.username,
            "latency_ms": r.latency_ms,
        }


class RequestLogService:
    """HTTP 调用明细用例：写入 request_logs（统计见 ``modules.logger.stats.RequestStats``）。"""

    def __init__(self, repo: object):
        """初始化。

        Args:
            repo: 通用仓储（collection="request_logs"，返回 RequestLog 实体）。
        """
        self._repo = repo

    def record(self, method: str, path: str, status_code: int,
               username: str | None = None, user_id: int | None = None,
               latency_ms: int | None = None) -> None:
        """记录一次调用（``is_error`` 由 status_code >= 400 推出）。"""
        code = int(status_code or 0)
        self._repo.insert("request_logs", RequestLog(
            method=(method or "").upper(),
            path=path or "",
            status_code=code,
            is_error=code >= 400,
            user_id=user_id,
            username=username or None,
            latency_ms=latency_ms,
            created_at=datetime.now().isoformat(timespec="seconds"),
        ))
