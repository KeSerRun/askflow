"""工具缓存：委托 adapters.cache.InMemoryCache（get/set/clear 入口）。

供工具 handler 缓存检索/网页结果，统一走 Cache 实现。
"""
from __future__ import annotations

from infra.adapters.cache import InMemoryCache

_cache = InMemoryCache()
_ttl = 300  # 5 分钟


def get(key: str) -> str | None:
    """读取缓存，过期或不存在返回 None。"""
    return _cache.get(key)


def set(key: str, content: str):
    """写入缓存（TTL 300s）。"""
    _cache.set(key, content, ttl=_ttl)


def clear():
    """清空缓存。"""
    _cache.clear()