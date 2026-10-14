"""CachedVectorStore 单元测试：读缓存命中 + 写操作版本失效（含 metadata）。"""

import unittest

from infra.adapters.cache import InMemoryCache
from infra.adapters.vector.cached import CachedVectorStore


class FakeVectorStore:
    """最小向量库替身：记录各读方法的调用次数。"""

    def __init__(self):
        self.data: list[dict] = []
        self.calls = {"metadata": 0, "sources": 0, "count": 0}

    @property
    def metadata(self):
        self.calls["metadata"] += 1
        return [dict(d) for d in self.data]

    def get_sources(self):
        self.calls["sources"] += 1
        return sorted({d["source"] for d in self.data if d.get("source")})

    def get_documents(self):
        return self.get_sources()

    def count(self):
        self.calls["count"] += 1
        return len(self.data)

    def add_documents(self, docs):
        self.data.extend(docs)

    def delete_all(self):
        self.data = []


class CachedVectorStoreTest(unittest.TestCase):
    def setUp(self):
        self.store = FakeVectorStore()
        self.store.data = [{"source": "a.pdf"}, {"source": "a.pdf"}, {"source": "b.pdf"}]
        self.cached = CachedVectorStore(self.store, InMemoryCache(), ttl=30)

    def test_metadata_cached(self):
        first = self.cached.metadata
        second = self.cached.metadata
        # 只真正查询一次（第二次命中缓存）
        self.assertEqual(self.store.calls["metadata"], 1)
        self.assertEqual(len(first), 3)
        self.assertEqual(len(second), 3)

    def test_sources_and_count_cached(self):
        self.cached.get_sources()
        self.cached.get_sources()
        self.cached.count()
        self.cached.count()
        self.assertEqual(self.store.calls["sources"], 1)
        self.assertEqual(self.store.calls["count"], 1)

    def test_write_invalidates_metadata(self):
        self.cached.metadata
        self.assertEqual(self.store.calls["metadata"], 1)
        # 经装饰器写入 → 版本 +1 → 旧缓存失效
        self.cached.add_documents([{"source": "c.pdf"}])
        fresh = self.cached.metadata
        self.assertEqual(self.store.calls["metadata"], 2)
        self.assertEqual(len(fresh), 4)

    def test_delete_all_invalidates(self):
        self.cached.count()
        self.cached.delete_all()
        self.assertEqual(self.cached.count(), 0)
        self.assertEqual(self.store.calls["count"], 2)


if __name__ == "__main__":
    unittest.main()
