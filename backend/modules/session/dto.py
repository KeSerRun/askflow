"""modules/session/dto.py —— 会话入参。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class SessionIdBody(BaseModel):
    """仅含 session_id 的请求体（session/history/query-cancel 共用，归属会话模块）。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    session_id: str = Field(min_length=1)
