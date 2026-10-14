"""modules/auth/dto.py —— 认证入参。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class Credentials(BaseModel):
    """注册 / 登录请求体。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    username: str = Field(min_length=1)
    password: str = Field(min_length=1)
