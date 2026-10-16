"""infra.adapters.vector.cached —— 给向量库加"读缓存、写失效"。

缓存读取（分区来源列表 / 数量 / 元数据）；写操作（入库 / 删除）后版本自增，旧缓存自然失效。
未覆写的属性/方法（dimension / search ...）经 __getattr__ 透传。
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

    @property
    def metadata(self) -> list:
        """chunk 元数据（全量 query Milvus，较重）——缓存，写操作后版本失效。"""
        return self._read("metadata", (), lambda: self._store.metadata)

    def get_sources(self):
        return self._read("sources", (),
                          lambda: self._store.get_sources())

    def get_documents(self):
        return self._read("sources", (),
                          lambda: self._store.get_documents())

    def count(self) -> int:
        return self._read("count", (), lambda: self._store.count())

    def get_partitions(self) -> list[str]:
        return self._read("partitions", (), lambda: self._store.get_partitions())

    # ── 写（失效） ──

    def add_documents(self, documents):
        result = self._store.add_documents(documents)
        self._bump()
        return result

    def store_documents_from_dir(self, directory, partition: str):
        """入库（写操作，结束后使读缓存失效）。

        ``partition`` 为知识库名（向量库 partition 字段值），需与底层实现保持一致。
        """
        result = self._store.store_documents_from_dir(directory, partition)
        self._bump()
        return result

    def delete_by_sources(self, sources, partition=None):
        result = self._store.delete_by_sources(sources, partition)
        self._bump()
        return result

    def delete_by_doc_ids(self, doc_ids, partition=None):
        """按 doc_id 删除（文档视图「移除」用）—— 必须 bump，否则 md_view 会读到 30s 旧缓存。"""
        result = self._store.delete_by_doc_ids(doc_ids, partition)
        self._bump()
        return result

    def delete_all(self):
        result = self._store.delete_all()
        self._bump()
        return result
