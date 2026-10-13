"""infra.adapters.vector.cached —— 给向量库加"读缓存、写失效"。

缓存读取（分区来源列表 / 数量）；写操作（入库 / 删除）后版本自增，旧缓存自然失效。
未覆写的属性/方法（metadata / dense_vectors / dimension / search ...）经 __getattr__ 透传。
"""

from __future__ import annotations

import json


class CachedVectorStore:
    """向量库缓存装饰器（透传未覆写成员）。"""

    def __init__(self, store: object, cache: object, *, ttl: int = 30):
        """初始化。

        Args:
            store: 底层向量库适配器。
            cache: 同步 Cache 适配器（InMemoryCache / RedisCache）。
            ttl: 读缓存过期秒数。
        """
        self._store = store
        self._cache = cache
        self._ttl = ttl

    def __getattr__(self, name):
        return getattr(self._store, name)

    # ── 版本 ──

    def _version(self) -> int:
        v = self._cache.get("cvec:ver")
        return int(v) if isinstance(v, int) else 0

    def _bump(self) -> None:
        self._cache.set("cvec:ver", self._version() + 1, ttl=0)

    def _read(self, method: str, args: tuple, loader):
        key = f"cvec:{self._version()}:{method}:{json.dumps(args, default=str, ensure_ascii=False)}"
        hit = self._cache.get(key)
        if isinstance(hit, dict) and "v" in hit:
            return hit["v"]
        value = loader()
        self._cache.set(key, {"v": value}, ttl=self._ttl)
        return value

    # ── 读（缓存） ──

    def get_sources(self):
        return self._read("sources", (),
                          lambda: self._store.get_sources())

    def get_documents(self):
        return self._read("sources", (),
                          lambda: self._store.get_documents())

    def count(self) -> int:
        return self._read("count", (), lambda: self._store.count())

    # ── 写（失效） ──

    def add_documents(self, documents):
        result = self._store.add_documents(documents)
        self._bump()
        return result

    def store_documents_from_dir(self, directory):
        result = self._store.store_documents_from_dir(directory)
        self._bump()
        return result

    def delete_by_sources(self, sources):
        result = self._store.delete_by_sources(sources)
        self._bump()
        return result

    def delete_all(self):
        result = self._store.delete_all()
        self._bump()
        return result
