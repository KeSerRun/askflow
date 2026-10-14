"""modules/logger/entity.py —— 应用日志 / 调用记录的数据库记录（ORM 领域模型）。"""

from __future__ import annotations

from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy.orm import mapped_column

from infra.adapters.storage import Base


class AppLog(Base):
    """一条应用日志（app.log 的数据库镜像）。"""

    __tablename__ = "app_logs"

    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at = mapped_column(String(40), nullable=False)
    level = mapped_column(String(16), nullable=False)
    logger = mapped_column(String(64), nullable=False)
    module = mapped_column(String(64), nullable=True)
    lineno = mapped_column(Integer, nullable=True)
    message = mapped_column(Text, nullable=False)


class RequestLog(Base):
    """一条 HTTP 调用记录（ORM 模型即领域模型）。"""

    __tablename__ = "request_logs"

    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    method = mapped_column(String(10), nullable=False)
    path = mapped_column(String(512), nullable=False)
    status_code = mapped_column(Integer, nullable=False)
    is_error = mapped_column(Boolean, nullable=False, default=False)
    user_id = mapped_column(Integer, nullable=True, index=True)    # 关联用户（users.id，可空=未登录）
    username = mapped_column(String(64), nullable=True)
    latency_ms = mapped_column(Integer, nullable=True)
    created_at = mapped_column(String(40), nullable=False)
