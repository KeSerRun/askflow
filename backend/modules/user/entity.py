"""modules/user/entity.py —— 用户 ORM 领域模型。"""

from __future__ import annotations

from sqlalchemy import Integer, String
from sqlalchemy.orm import mapped_column

from infra.adapters.storage import Base


class User(Base):
    """用户实体（ORM 模型即领域模型）。"""

    __tablename__ = "users"

    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    username = mapped_column(String(64), unique=True, nullable=False)
    password = mapped_column(String(255), nullable=False)
    role = mapped_column(String(32), nullable=False, default="user")
    created_at = mapped_column(String(40), nullable=False)
