"""modules/logger/db_handler.py —— 应用日志的数据库落盘 Handler。

给 ``APPLogger`` 附加一个写库 Handler，让 app.log 的内容同时进入 ``app_logs`` 表。
失败一律静默，且用互斥标志防止「写库失败再触发日志」造成递归。
"""

from __future__ import annotations

import logging
from datetime import datetime

from config import conf
from .entity import AppLog


class DatabaseLogHandler(logging.Handler):
    """把应用日志同步写入 ``app_logs`` 表（失败静默，防递归）。"""

    _busy = False

    def __init__(self, repo: object):
        """初始化。

        Args:
            repo: 通用仓储（collection="app_logs"）。
        """
        super().__init__()
        self._repo = repo
        self.setFormatter(logging.Formatter("%(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        # 互斥 + 防递归：同一时刻只允许一次写入
        if DatabaseLogHandler._busy:
            return
        DatabaseLogHandler._busy = True
        try:
            try:
                self._repo.insert("app_logs", AppLog(
                    created_at=datetime.fromtimestamp(record.created).isoformat(timespec="seconds"),
                    level=record.levelname,
                    logger=record.name,
                    module=record.module,
                    lineno=record.lineno,
                    message=self.format(record),
                ))
            except Exception:
                pass  # 写库失败静默，避免递归
        finally:
            DatabaseLogHandler._busy = False


_attached = False


def attach_application_db_logger(repo: object) -> DatabaseLogHandler | None:
    """把 DB Handler 挂到 ``APPLogger``（幂等，重复调用不叠加）。

    生产（APP_ENV=production）下 DB 只存 ERROR 及以上，INFO 不入库。
    """
    global _attached
    if _attached:
        return None
    _attached = True
    handler = DatabaseLogHandler(repo)
    _prod = str(getattr(conf, "app_env", "") or "").strip().lower() in ("production", "prod")
    handler.setLevel(logging.ERROR if _prod else (conf.log_app_level or logging.INFO))
    logging.getLogger("APPLogger").addHandler(handler)
    return handler