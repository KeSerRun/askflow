"""modules/auth/entity.py —— 认证领域实体与 refresh token ORM 模型。"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Integer, String
from sqlalchemy.orm import mapped_column

from infra.adapters.storage import Base


@dataclass(frozen=True)
class AuthenticatedUser:
    """登录/刷新成功后的用户身份与令牌对。

    - ``access_token``：短时效 JWT，前端放内存、经 ``Authorization`` 头携带；
    - ``refresh_token``：不透明长时效令牌，走 httpOnly cookie，仅用于换新 access。
    """

    username: str
    role: str
    access_token: str
    refresh_token: str


class RefreshToken(Base):
    """refresh token 存储：只存哈希 + 归属，令牌本身不落库。"""

    __tablename__ = "refresh_tokens"

    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    username = mapped_column(String(64), nullable=False, index=True)
    role = mapped_column(String(32), nullable=False)
    token_hash = mapped_column(String(64), unique=True, nullable=False)
    expires_at = mapped_column(Integer, nullable=False)