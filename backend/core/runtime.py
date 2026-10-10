"""core.runtime —— Web 运行时共享状态（模块级单例，非 HTTP 层专属）。"""

from __future__ import annotations

import threading
import time


class RequestStats:
    """线程安全的请求统计累加器。

    在内存中记录请求总数、错误数、按 HTTP 方法分类的计数器，
    供管理后台仪表盘读取和展示。

    Attributes:
        _lock: 线程锁。
        total_requests: 总请求数。
        total_errors: 总错误数（状态码 >= 400）。
        by_method: 按 HTTP 方法统计的请求数字典。
        start_time: 应用启动时间戳。
    """

    def __init__(self):
        self._lock = threading.Lock()
        self.total_requests = 0
        self.total_errors = 0
        self.by_method: dict[str, int] = {}
        self.start_time = time.time()

    def record(self, method: str, path: str, status_code: int):
        """记录一次请求（每次请求处理完毕后调用）。"""
        with self._lock:
            self.total_requests += 1
            if status_code >= 400:
                self.total_errors += 1
            self.by_method[method.upper()] = self.by_method.get(method.upper(), 0) + 1


# 进程级请求统计器（app 中间件写入、仪表盘读取）
request_stats = RequestStats()