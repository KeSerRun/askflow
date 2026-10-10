"""adapters.cache.redis_cache —— Redis 缓存（跨实例共享）。

依赖 redis 包（未安装时仅在构造时提示，不阻塞导入）。
"""

from __future__ import annotations

import json
from typing import Any, Optional



class RedisCache:
    """基于 Redis 的缓存实现。"""

    def __init__(self, url: str):
        """初始化。

        Args:
            url: redis://[user:pass@]host:port/db。

        Raises:
            ImportError: 未安装 redis 依赖。
        """
        try:
            import redis  # 延迟导入
        except ImportError as e:  # pragma: no cover
            raise ImportError("RedisCache 需要安装 redis 依赖: pip install redis") from e
        self._r = redis.from_url(url)

    def get(self, key: str) -> Optional[Any]:
        raw = self._r.get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            return raw.decode("utf-8", "ignore") if isinstance(raw, bytes) else raw

    def set(self, key: str, value: Any, ttl: int = 300) -> None:
        self._r.set(key, json.dumps(value, ensure_ascii=False), ex=(ttl or None))

    def delete(self, key: str) -> bool:
        return bool(self._r.delete(key))

    def clear(self) -> None:
        self._r.flushdb()