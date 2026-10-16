"""CachedVectorStore 单元测试：读缓存命中 + 写操作版本失效（含 metadata）。"""

import inspect
import unittest

from infra.adapters.cache import InMemoryCache
from infra.adapters.vector import MilvusVectorStore
from infra.adapters.vector.cached import CachedVectorStore


class FakeVectorStore:
    """最小向量库替身：记录各读方法的调用次数。"""

    def __init__(self):
        self.data: list[dict] = []
        self.calls = {"metadata": 0, "sources": 0, "count": 0, "partitions": 0,
                      "by_sources": 0, "by_doc_ids": 0}
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

    def store_documents_from_dir(self, directory, partition):
        self.stored.append((directory, partition))

    def delete_all(self):
        self.data = []

    def delete_by_sources(self, sources, partition=None):
        self.calls["by_sources"] += 1
        names = set(sources or [])
        self.data = [d for d in self.data if d.get("source") not in names]

    def delete_by_doc_ids(self, ids, partition=None):
        self.calls["by_doc_ids"] += 1
        ids = set(ids or [])
        self.data = [d for d in self.data if d.get("doc_id") not in ids]


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

    def test_delete_by_sources_invalidates(self):
        """按来源删除后，读缓存必须失效（否则文档列表会显示已删的文档）。"""
        self.cached.get_sources()
        self.assertEqual(self.store.calls["sources"], 1)
        self.cached.delete_by_sources(["b.pdf"])
        self.assertEqual(self.store.get_sources(), ["a.pdf"])
        self.assertEqual(self.store.calls["sources"], 2)

    def test_delete_by_doc_ids_invalidates(self):
        """按 doc_id 删除后必须让 metadata 失效 —— 文档视图「移除」依赖它。

        回归：``delete_by_doc_ids`` 曾漏覆写（透传底层但不 bump），导致移除后
        ``md_view`` 在 30s 内仍返回 ``marked=true``，前端看不到同步更新。
        """
        self.store.data.append({"source": "c.pdf", "doc_id": "x1"})
        self.cached.metadata
        self.assertEqual(self.store.calls["metadata"], 1)
        self.cached.delete_by_doc_ids(["x1"])
        fresh = self.cached.metadata
        self.assertEqual(self.store.calls["metadata"], 2)   # 缓存已失效，重新查询底层
        self.assertEqual(len(fresh), 3)
        self.assertIsNone(next((d for d in fresh if d.get("doc_id") == "x1"), None))

    def test_partitions_cached(self):
        self.store.data.append({"source": "c.pdf", "partition": "kbA"})
        self.assertEqual(self.cached.get_partitions(), ["kbA"])
        self.assertEqual(self.cached.get_partitions(), ["kbA"])
        self.assertEqual(self.store.calls["partitions"], 1)

    def test_store_documents_from_dir_forwards_partition(self):
        """装饰器必须把 partition 透传给底层实现（否则入库报参数错误）。"""
        self.cached.store_documents_from_dir("/tmp/a.pdf", "产品手册")
        self.assertEqual(self.store.stored, [("/tmp/a.pdf", "产品手册")])

    def test_store_documents_from_dir_requires_partition(self):
        """partition 无默认值（不再假设 __system__）—— 入库必须显式指定知识库。"""
        with self.assertRaises(TypeError):
            self.cached.store_documents_from_dir("/tmp/a.pdf")

    def test_store_documents_from_dir_invalidates_cache(self):
        self.store.data.append({"source": "c.pdf", "partition": "kbA"})
        self.assertEqual(self.cached.get_partitions(), ["kbA"])
        self.cached.store_documents_from_dir("/tmp/a.pdf", "kbA")
        self.assertEqual(self.cached.get_partitions(), ["kbA"])
        self.assertEqual(self.store.calls["partitions"], 2)  # 写后读缓存已失效

    def test_override_signatures_match_milvus(self):
        """装饰器覆写的方法签名必须与真实 MilvusVectorStore 一致。

        装饰器一律按 ``(args..., partition)`` 位置转发；只要底层少一个参数就会
        抛 ``TypeError: takes N positional arguments but N+1 were given``。
        这个坑已经踩过两次（``store_documents_from_dir``、``delete_by_doc_ids``），
        所以直接拿真实类比对签名，而不是比对测试替身。
        """
        overridden = ("add_documents", "store_documents_from_dir",
                      "delete_by_sources", "delete_by_doc_ids", "delete_all")
        for name in overridden:
            wrapper = list(inspect.signature(getattr(CachedVectorStore, name)).parameters)
            real = list(inspect.signature(getattr(MilvusVectorStore, name)).parameters)
            self.assertEqual(wrapper, real, f"{name} 装饰器签名与 MilvusVectorStore 不一致")

    def test_overridden_methods_all_bump(self):
        """每个覆写都要真的让缓存失效（防止再出现「后端说成功、前端读旧值」）。"""
        overridden = ("add_documents", "store_documents_from_dir",
                      "delete_by_sources", "delete_by_doc_ids", "delete_all")
        for name in overridden:
            store = FakeVectorStore()
            cached = CachedVectorStore(store, InMemoryCache(), ttl=30)
            cached.metadata                      # 先填缓存
            self.assertEqual(store.calls["metadata"], 1)
            if name == "add_documents":
                cached.add_documents([])
            elif name == "store_documents_from_dir":
                cached.store_documents_from_dir("/tmp/x.pdf", "kbA")
            elif name == "delete_by_sources":
                cached.delete_by_sources([])
            elif name == "delete_by_doc_ids":
                cached.delete_by_doc_ids([])
            else:
                cached.delete_all()
            cached.metadata
            self.assertEqual(store.calls["metadata"], 2, f"{name} 未使读缓存失效")


if __name__ == "__main__":
    unittest.main()
