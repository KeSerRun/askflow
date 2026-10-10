"""adapters.cache.inmemory —— 进程内字典缓存（TTL 过期）。"""

from __future__ import annotations

import threading
import time
from typing import Any, Optional



class InMemoryCache:
    """进程内键值缓存。"""

    def __init__(self):
        self._data: dict[str, tuple[Any, float]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return None
            value, expire_ts = entry
            if expire_ts and time.time() > expire_ts:
                del self._data[key]
                return None
            return value

    def set(self, key: str, value: Any, ttl: int = 300) -> None:
        expire_ts = time.time() + ttl if ttl > 0 else 0.0
        with self._lock:
            self._data[key] = (value, expire_ts)

    def delete(self, key: str) -> bool:
        with self._lock:
            return self._data.pop(key, None) is not None

    def clear(self) -> None:
        with self._lock:
            self._data.clear()