"""core.security —— JWT 取用与校验（纯函数，不依赖 HTTP 框架）。

供依赖（core.deps）与中间件（core.middleware）共用：集中 token 提取与 access
token 校验，避免各处重复实现。
"""

from __future__ import annotations

import jwt

from config import conf


def extract_bearer(request) -> str | None:
    """从 ``Authorization: Bearer`` 头取原始 token（无则 None）。"""
    header = request.headers.get("Authorization")
    if header and header.startswith("Bearer "):
        return header.split(" ", 1)[1]
    return None


def decode_access_token(raw: str | None) -> dict | None:
    """校验 access token 并返回 payload。

    Args:
        raw: 原始 JWT 字符串（可为 None）。

    Returns:
        合法且为 access 类型时返回 payload；缺失/非法/非 access 返回 None。
    """
    if not raw:
        return None
    try:
        payload = jwt.decode(raw.encode("utf-8"), conf.auth_jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    if not payload.get("username") or payload.get("type") != "access":
        return None
    return payload
