"""infra.adapters.storage.cached_repo —— 给任意 Repo 加"读缓存、写失效"。

按``集合``维护版本号：写操作后版本自增，旧缓存键自然不再命中（TTL 兜底清理）。
读方法 ``get/find/count`` 走缓存；写方法 ``insert/update/update_where/delete/delete_where``
后 bump 该集合版本。

底层仓储读写的是 ORM 实例；缓存内保存**纯 dict 形式**（便于 InMemory/Redis 序列化），
命中时按集合重建 ORM 实例返回。
"""

from __future__ import annotations

import json
from contextlib import contextmanager

from .orm import row_from_dict, row_to_dict

_SENTINEL = "v"  # 包一层，保证 None/[] 也能被缓存区分
_PLAIN = (dict, int, float, str, bool, type(None))


class CachedRepo:
    """数据访问层缓存装饰器（实现与 Repo 相同的鸭子接口）。"""

    def __init__(self, repo: object, cache: object, *, ttl: int = 120):
        """初始化。

        Args:
            repo: 底层 Repo（SqliteRepo / MySQLRepo）。
            cache: 同步 Cache 适配器（InMemoryCache / RedisCache）。
            ttl: 读缓存过期秒数。
        """
        self._repo = repo
        self._cache = cache
        self._ttl = ttl

    # ── 事务（透传） ──

    @contextmanager
    def transaction(self):
        """透传底层 Repo 的显式事务（SQL 仓储实现）。"""
        with self._repo.transaction() as s:
            yield s

    # ── 版本 ──

    def _version(self, collection: str) -> int:
        v = self._cache.get(f"crepo:ver:{collection}")
        return int(v) if isinstance(v, int) else 0

    def _bump(self, collection: str) -> None:
        self._cache.set(f"crepo:ver:{collection}", self._version(collection) + 1, ttl=0)

    # ── 缓存序列化（ORM 实例 ↔ 纯 dict） ──

    @staticmethod
    def _dump(value):
        if isinstance(value, list):
            return [v if isinstance(v, _PLAIN) else row_to_dict(v) for v in value]
        return value if isinstance(value, _PLAIN) else row_to_dict(value)

    @staticmethod
    def _restore(collection: str, value):
        if isinstance(value, list):
            return [row_from_dict(collection, d) if isinstance(d, dict) else d for d in value]
        if isinstance(value, dict):
            return row_from_dict(collection, value)
        return value

    def _read(self, collection: str, method: str, args: tuple, loader):
        key = f"crepo:{collection}:{self._version(collection)}:{method}:" \
              f"{json.dumps(args, sort_keys=True, default=str, ensure_ascii=False)}"
        hit = self._cache.get(key)
        if isinstance(hit, dict) and _SENTINEL in hit:
            return self._restore(collection, hit[_SENTINEL])
        value = loader()
        self._cache.set(key, {_SENTINEL: self._dump(value)}, ttl=self._ttl)
        return value

    # ── 读（缓存；带 session 时穿透） ──

    def get(self, collection: str, doc_id, session=None):
        if session is not None:
            return self._repo.get(collection, doc_id, session=session)
        return self._read(collection, "get", (doc_id,),
                          lambda: self._repo.get(collection, doc_id))

    def find(self, collection: str, where=None, *, order_by=None, offset=0, limit=None, session=None):
        if session is not None:
            return self._repo.find(collection, where, order_by=order_by,
                                   offset=offset, limit=limit, session=session)
        args = (where, order_by, offset, limit)
        return self._read(collection, "find", args, lambda: self._repo.find(
            collection, where, order_by=order_by, offset=offset, limit=limit))

    def count(self, collection: str, where=None, session=None):
        if session is not None:
            return self._repo.count(collection, where, session=session)
        return self._read(collection, "count", (where,),
                          lambda: self._repo.count(collection, where))

    # ── 写（失效该集合） ──

    def insert(self, collection: str, entity, session=None):
        result = self._repo.insert(collection, entity, session=session)
        self._bump(collection)
        return result

    def update(self, collection: str, doc_id, fields: dict, session=None) -> bool:
        result = self._repo.update(collection, doc_id, fields, session=session)
        self._bump(collection)
        return result

    def update_where(self, collection: str, where: dict, fields: dict, session=None) -> int:
        result = self._repo.update_where(collection, where, fields, session=session)
        self._bump(collection)
        return result

    def delete(self, collection: str, doc_id, session=None) -> bool:
        result = self._repo.delete(collection, doc_id, session=session)
        self._bump(collection)
        return result

    def delete_where(self, collection: str, where: dict, session=None) -> int:
        result = self._repo.delete_where(collection, where, session=session)
        self._bump(collection)
        return result