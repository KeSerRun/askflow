"""modules/session/entity.py —— 会话 ORM 领域模型。"""

from __future__ import annotations

from sqlalchemy import Integer, String
from sqlalchemy.orm import mapped_column

from infra.adapters.storage import Base


class Session(Base):
    """会话实体（ORM 模型即领域模型）。"""

    __tablename__ = "sessions"

    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id = mapped_column(String(64), unique=True, nullable=False)
    username = mapped_column(String(64), nullable=False)
    created_at = mapped_column(String(40), nullable=False)