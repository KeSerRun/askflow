"""adapters.storage.mysql_repo —— MySQL 后端（连接池健康检查）。"""

from __future__ import annotations

from sqlalchemy import create_engine

from .sql_base import SqlAlchemyRepo


class MySQLRepo(SqlAlchemyRepo):
    """MySQL 通用对象仓储（``mysql+pymysql://user:pass@host:port/db``）。"""

    def _create_engine(self, url: str):
        return create_engine(
            url,
            pool_pre_ping=True,
            pool_recycle=3600,
            pool_size=10,      # 池里常驻的空闲连接数
            max_overflow=20,   # 高并发时可临时多开的连接数（最多 10+20=30）
            pool_timeout=10,   # 池被占满时，等一个连接的超时秒数
            future=True,
        )