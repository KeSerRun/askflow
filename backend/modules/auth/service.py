"""modules.auth.service —— 认证用例（注册 / 登录 / 刷新令牌轮换 / 登出）。

只依赖注入的具体实现，不感知 FastAPI、全局配置或存储细节。
用户名规范化、唯一性、凭据校验、双令牌（access/refresh）签发等业务规则集中于此。

令牌模型：
- access token：短时效 JWT（带 ``exp`` 与 ``type=access``），前端内存 + Bearer 头；
- refresh token：不透明随机串，只在服务端存 **SHA-256 哈希**；经 httpOnly cookie 下发，
  仅 ``refresh()`` 使用；每次刷新即**轮换**（作废旧、发新），旧令牌再使用会失败。
"""

from __future__ import annotations

import hashlib
import secrets
import time
from typing import Optional

import jwt

from core.app_errors import (
    AuthError,  # noqa: F401
    InvalidCredentials,
    InvalidRefreshToken,
    UsernameAlreadyExists,
)
from .entity import AuthenticatedUser, RefreshToken

REFRESH_COLLECTION = "refresh_tokens"


def normalize_username(username: str) -> str:
    """用户名规范化：去除首尾空白（**保留输入大小写**，登录时大小写不敏感匹配）。"""
    return username.strip()


class _MemoryRefreshStore:
    """无仓储注入时的兜底内存实现（供单元测试/独立使用）。"""

    def __init__(self):
        self._rows: list = []
        self._seq = 0

    def insert(self, collection: str, entity, session=None):
        self._seq += 1
        entity.id = self._seq
        self._rows.append(entity)
        return self._seq

    def find(self, collection: str, where=None, *, order_by=None, offset=0, limit=None, session=None):
        return [r for r in self._rows
                if all(getattr(r, k, None) == v for k, v in (where or {}).items())]

    def delete_where(self, collection: str, where: dict, session=None):
        keep = [r for r in self._rows
                if not all(getattr(r, k, None) == v for k, v in where.items())]
        n = len(self._rows) - len(keep)
        self._rows = keep
        return n


class AuthService:
    """认证服务：注册、登录、令牌签发与刷新轮换。"""

    def __init__(
        self,
        users: object,
        *,
        jwt_secret: str,
        jwt_algorithm: str = "HS256",
        refresh_store: object | None = None,
        access_ttl_seconds: int = 30 * 60,
        refresh_ttl_seconds: int = 7 * 24 * 3600,
    ):
        """初始化。

        Args:
            users: 用户存储端口（提供 insert_user / check_user_credentials）。
            jwt_secret: JWT 签名密钥（由组合根注入，服务不读全局配置）。
            jwt_algorithm: JWT 签名算法。
            refresh_store: 通用仓储（collection `refresh_tokens` 落库轮换状态）；
                不传则用内存兜底（仅测试/独立使用）。
            access_ttl_seconds: access token 有效期（秒），默认 30 分钟。
            refresh_ttl_seconds: refresh token 有效期（秒），默认 7 天。
        """
        self._users = users
        self._secret = jwt_secret
        self._algorithm = jwt_algorithm
        self._store = refresh_store or _MemoryRefreshStore()
        self._access_ttl = access_ttl_seconds
        self._refresh_ttl = refresh_ttl_seconds

    def register(self, username: str, password: str) -> None:
        """注册新用户。

        Raises:
            UsernameAlreadyExists: 用户名已存在。
        """
        username = normalize_username(username)
        if not self._users.insert_user(username, password):
            raise UsernameAlreadyExists(username)

    def login(self, username: str, password: str) -> AuthenticatedUser:
        """校验凭据并签发 access + refresh 令牌对。

        Raises:
            InvalidCredentials: 用户名或密码不匹配。
        """
        username = normalize_username(username)
        row = self._users.check_user_credentials(username, password)
        if not row:
            raise InvalidCredentials(username)
        return self._issue(row["username"], row["role"], row.get("user_id"))

    def refresh(self, refresh_token: str) -> AuthenticatedUser:
        """用 refresh token 换取新的令牌对（轮换：作废旧 refresh）。

        Raises:
            InvalidRefreshToken: 令牌缺失 / 过期 / 已被轮换（重用旧令牌）。
        """
        token_hash = self._hash(refresh_token)
        rows = self._store.find(REFRESH_COLLECTION, {"token_hash": token_hash})
        if not rows:
            raise InvalidRefreshToken()
        row = rows[0]
        if row.expires_at <= int(time.time()):
            self._store.delete_where(REFRESH_COLLECTION, {"token_hash": token_hash})
            raise InvalidRefreshToken("refresh token expired")
        # 轮换：先作废旧令牌，再签发新对
        self._store.delete_where(REFRESH_COLLECTION, {"token_hash": token_hash})
        return self._issue(row.username, row.role, getattr(row, "user_id", None))

    def logout(self, refresh_token: str) -> int:
        """按 refresh token 吊销该用户全部 refresh 令牌（多端同时登出）。"""
        rows = self._store.find(REFRESH_COLLECTION, {"token_hash": self._hash(refresh_token)})
        if not rows:
            return 0
        return self._store.delete_where(REFRESH_COLLECTION, {"username": rows[0].username})

    def decode(self, token: str) -> Optional[dict]:
        """校验并解析 access token；失败或非 access 类型返回 None。"""
        try:
            payload = jwt.decode(token.encode("utf-8"), self._secret, algorithms=[self._algorithm])
        except jwt.PyJWTError:
            return None
        return payload if payload.get("type") == "access" else None

    def revoke_user(self, username: str) -> int:
        """吊销某用户所有 refresh 令牌（改密/封禁等场景）。"""
        return self._store.delete_where(REFRESH_COLLECTION, {"username": username})

    # ── 内部 ──

    def _issue(self, username: str, role: str, user_id=None) -> AuthenticatedUser:
        """签发 access JWT（含 user_id）+ 随机 refresh（哈希入库）。"""
        claims = {
            "username": username,
            "role": role,
            "type": "access",
            "exp": int(time.time()) + self._access_ttl,
        }
        if user_id is not None:
            claims["user_id"] = user_id
        access = jwt.encode(claims, self._secret, algorithm=self._algorithm)
        refresh = secrets.token_urlsafe(48)
        self._store.insert(REFRESH_COLLECTION, RefreshToken(
            user_id=user_id,
            username=username,
            role=role,
            token_hash=self._hash(refresh),
            expires_at=int(time.time()) + self._refresh_ttl,
        ))
        return AuthenticatedUser(user_id=user_id, username=username, role=role,
                                 access_token=access, refresh_token=refresh)

    @staticmethod
    def _hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()