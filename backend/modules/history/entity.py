"""modules/history/entity.py —— 对话历史 ORM 领域模型。"""

from __future__ import annotations

from sqlalchemy import JSON, Integer, String, Text
from sqlalchemy.orm import mapped_column

from infra.adapters.storage import Base


class HistoryEntry(Base):
    """一条历史记录（qa / turn / event；ORM 模型即领域模型）。"""

    __tablename__ = "history"

    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id = mapped_column(String(64), nullable=False)
    type = mapped_column(String(16), nullable=False)
    user = mapped_column("user_msg", Text, nullable=True)
    assistant = mapped_column("assistant_msg", Text, nullable=True)
    messages = mapped_column(JSON, nullable=True)
    event_type = mapped_column(String(32), nullable=True)
    files = mapped_column(JSON, nullable=True)
    archived = mapped_column(Integer, default=0, nullable=False)
    timestamp = mapped_column(String(40), nullable=False)