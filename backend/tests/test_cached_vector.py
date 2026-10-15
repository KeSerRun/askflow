"""CachedVectorStore 单元测试：读缓存命中 + 写操作版本失效（含 metadata）。"""

import unittest

from infra.adapters.cache import InMemoryCache
from infra.adapters.vector.cached import CachedVectorStore


class FakeVectorStore:
    """最小向量库替身：记录各读方法的调用次数。"""

    def __init__(self):
        self.data: list[dict] = []
        self.calls = {"metadata": 0, "sources": 0, "count": 0, "partitions": 0}
        self.stored: list[tuple] = []   # (directory, partition)

    @property
    def metadata(self):
        self.calls["metadata"] += 1
        return [dict(d) for d in self.data]

    def get_sources(self):
        self.calls["sources"] += 1
        return sorted({d["source"] for d in self.data if d.get("source")})

    def get_documents(self):
        return self.get_sources()

    def get_partitions(self):
        self.calls["partitions"] += 1
        return sorted({d["partition"] for d in self.data if d.get("partition")})

    def count(self):
        self.calls["count"] += 1
        return len(self.data)

    def add_documents(self, docs):
        self.data.extend(docs)

    def store_documents_from_dir(self, directory, partition="__system__"):
        self.stored.append((directory, partition))

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

    def test_partitions_cached(self):
        self.store.data.append({"source": "c.pdf", "partition": "kbA"})
        self.assertEqual(self.cached.get_partitions(), ["kbA"])
        self.assertEqual(self.cached.get_partitions(), ["kbA"])
        self.assertEqual(self.store.calls["partitions"], 1)

    def test_store_documents_from_dir_forwards_partition(self):
        """装饰器必须把 partition 透传给底层实现（否则入库报参数错误）。"""
        self.cached.store_documents_from_dir("/tmp/a.pdf", "产品手册")
        self.assertEqual(self.store.stored, [("/tmp/a.pdf", "产品手册")])

    def test_store_documents_from_dir_partition_defaults(self):
        self.cached.store_documents_from_dir("/tmp/a.pdf")
        self.assertEqual(self.store.stored, [("/tmp/a.pdf", "__system__")])

    def test_store_documents_from_dir_invalidates_cache(self):
        self.store.data.append({"source": "c.pdf", "partition": "kbA"})
        self.assertEqual(self.cached.get_partitions(), ["kbA"])
        self.cached.store_documents_from_dir("/tmp/a.pdf", "kbA")
        self.assertEqual(self.cached.get_partitions(), ["kbA"])
        self.assertEqual(self.store.calls["partitions"], 2)  # 写后读缓存已失效


if __name__ == "__main__":
    unittest.main()
