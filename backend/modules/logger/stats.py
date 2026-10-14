"""modules.logger.stats —— HTTP 请求统计（缓存内累加，独立于 request_logs 与环境）。

设计：
  - 每个 ``/api`` 请求调用 :meth:`RequestStats.incr` 在缓存里做 +1 累加；
  - 与 ``request_logs``（明细表，受生产/开发策略控制）**解耦**：统计恒为全量，
    不受 ``APP_ENV`` 影响，也不依赖任何 COUNT 查询（O(1) 读写）；
  - 存储在后端缓存（InMemoryCache / RedisCache），不落库。

注意：累加是"加锁的读-改-写"，单进程内安全；多进程/多实例共享同一个 Redis 时
存在竞争（当前 APP_WORKERS=1，无碍）。
"""

from __future__ import annotations

import threading
import time

_KEY = "reqstats"


class RequestStats:
    """请求统计累加器（缓存存储，无 DB、无 COUNT）。"""

    def __init__(self, cache: object | None = None):
        self._cache = cache
        self._lock = threading.Lock()
        self._mem: dict = {}  # 缓存不可用时的进程内兜底

    # ── 内部读写 ──

    def _get_agg(self) -> dict | None:
        if self._cache is not None:
            v = self._cache.get(_KEY)
            return dict(v) if isinstance(v, dict) else None
        return dict(self._mem) if self._mem else None

    def _set_agg(self, agg: dict) -> None:
        if self._cache is not None:
            self._cache.set(_KEY, agg, ttl=0)  # ttl=0 表示不过期（累计值常驻）
        else:
            self._mem = dict(agg)

    # ── 对外 ──

    def incr(self, method: str, status_code: int) -> None:
        """记录一次请求：total/errors/by_method 累加（不落库、不 COUNT）。"""
        m = (method or "").upper() or "-"
        code = int(status_code or 0)
        with self._lock:
            agg = self._get_agg() or {
                "total": 0, "errors": 0, "by_method": {}, "first_seen": time.time(),
            }
            agg["total"] = int(agg.get("total", 0)) + 1
            if code >= 400:
                agg["errors"] = int(agg.get("errors", 0)) + 1
            bm = agg.get("by_method") or {}
            bm[m] = int(bm.get(m, 0)) + 1
            agg["by_method"] = bm
            self._set_agg(agg)

    def snapshot(self) -> dict:
        """返回统计快照（供仪表盘；字段与原 request_stats 保持一致）。"""
        agg = self._get_agg() or {}
        total = int(agg.get("total", 0) or 0)
        errors = int(agg.get("errors", 0) or 0)
        by_method = dict(agg.get("by_method") or {})
        first = float(agg.get("first_seen") or 0) or time.time()
        return {
            "total_requests": total,
            "total_errors": errors,
            "by_method": by_method,
            "start_time": first,
            "uptime_seconds": int(max(0, time.time() - first)),
        }

    def reset(self) -> None:
        """清空统计。"""
        with self._lock:
            if self._cache is not None:
                self._cache.delete(_KEY)
            self._mem = {}
