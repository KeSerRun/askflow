"""modules/history/dto.py —— 历史入参。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class SessionIdBody(BaseModel):
    """仅含 session_id 的请求体（清除会话历史）。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    session_id: str = Field(min_length=1)