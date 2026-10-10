"""adapters —— Ports 的实现层。

每个子包对应一个 port，多个实现可共存；组合根按开关选择。
"""

from .cache import InMemoryCache, RedisCache  # noqa: F401
from .object import LocalObjectStore, MinioObjectStore  # noqa: F401
from .queue import InProcessTaskQueue  # noqa: F401

__all__ = ["LocalObjectStore", "MinioObjectStore", "InMemoryCache", "RedisCache", "InProcessTaskQueue"]