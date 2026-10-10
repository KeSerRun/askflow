"""modules/query/dto.py —— 问答入参。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class QueryBody(BaseModel):
    """问答请求体。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    session_id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    stream: bool = False
    style: str | None = None
    workflow: str | None = None


class SessionIdBody(BaseModel):
    """仅含 session_id 的请求体（中断问答）。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    session_id: str = Field(min_length=1)


class ResumeBody(BaseModel):
    """续跑请求体（断点续跑）。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    session_id: str = Field(min_length=1)
    extra_iterations: int = Field(default=0, ge=0, le=20)
