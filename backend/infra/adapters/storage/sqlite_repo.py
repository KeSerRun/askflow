"""adapters.storage.sqlite_repo —— SQLite 后端（文件库，自动建目录）。"""

from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

from .sql_base import SqlAlchemyRepo


class SqliteRepo(SqlAlchemyRepo):
    """SQLite 通用对象仓储（``sqlite:///path/to.db`` 或 ``sqlite:///:memory:``）。"""

    def _create_engine(self, url: str):
        self._ensure_dir(url)
        # check_same_thread=False：允许连接在 FastAPI 线程池/后台线程间复用
        return create_engine(url, future=True, connect_args={"check_same_thread": False})

    @staticmethod
    def _ensure_dir(url: str) -> None:
        """文件库需保证父目录存在（否则建库失败）。"""
        try:
            u = make_url(url)
        except Exception:
            return
        if u.database and u.database != ":memory:":
            parent = os.path.dirname(u.database)
            if parent:
                os.makedirs(parent, exist_ok=True)