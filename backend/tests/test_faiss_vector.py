"""FaissVectorStore 单元测试：入库/检索/分区过滤/删除/持久化。

使用 FakeEmbedder 产生确定性伪向量，避免依赖网络。
"""

import hashlib
import shutil
import tempfile
import unittest

from infra.adapters.vector import FaissVectorStore
from core.models import Document


class FakeEmbedder:
    """确定性伪嵌入：相同文本 → 相同向量。"""

    def __init__(self, dim: int = 16):
        self._dim = dim

    @property
    def dimension(self) -> int:
        return self._dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for t in texts:
            h = hashlib.md5(t.encode("utf-8")).digest()
            vec = [int(b) / 255.0 for b in h[: self._dim]]
            out.append(vec)
        return out


class FaissVectorStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.embedder = FakeEmbedder(dim=16)
        self.store = FaissVectorStore(self.embedder, index_dir=self.tmp, default_top_k=10)

    def tearDown(self):
        self.store = None
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _doc(self, content: str, source: str = "a.pdf", chunk_type: str = "text"):
        return Document(page_content=content, metadata={"source": source, "chunk_type": chunk_type})

    def test_add_and_search(self):
        self.store.add_documents([
            self._doc("苹果公司的营收增长强劲"),
            self._doc("人工智能在医疗领域的应用"),
        ])
        self.assertEqual(self.store.count(), 2)

        hits = self.store.search("苹果公司的营收增长强劲", top_k=5)
        self.assertGreaterEqual(len(hits), 1)
        self.assertEqual(hits[0].page_content, "苹果公司的营收增长强劲")

    def test_partition_filter(self):
        self.store.add_documents([self._doc("文档A-内容", source="a.pdf")], partition="p1")
        self.store.add_documents([self._doc("文档B-内容", source="b.pdf")], partition="p2")
        self.assertEqual(self.store.count(), 2)

        hits = self.store.search("文档B-内容", top_k=5, partition="p2")
        self.assertTrue(all("文档B" in d.page_content for d in hits))
        self.assertNotIn("文档A", [d.page_content for d in hits])

        self.assertEqual(self.store.get_sources_by_partition("p1"), ["a.pdf"])

    def test_delete_by_sources(self):
        self.store.add_documents([self._doc("内容A", source="a.pdf")], partition="p1")
        self.store.add_documents([self._doc("内容B", source="b.pdf")], partition="p1")
        self.store.delete_by_sources(["a.pdf"], partition="p1")
        self.assertEqual(self.store.count(), 1)
        self.assertEqual(self.store.get_sources_by_partition("p1"), ["b.pdf"])

    def test_delete_by_partition(self):
        self.store.add_documents([self._doc("A1", source="a.pdf")], partition="p1")
        self.store.add_documents([self._doc("B1", source="b.pdf")], partition="p2")
        self.store.delete_by_partition("p1")
        self.assertEqual(self.store.count(), 1)
        self.assertEqual(self.store.get_sources_by_partition(), ["b.pdf"])

    def test_persistence_roundtrip(self):
        self.store.add_documents([self._doc("可持续相关内容", source="c.pdf")], partition="p9")
        # 重新加载（模拟重启）
        store2 = FaissVectorStore(self.embedder, index_dir=self.tmp, default_top_k=10)
        self.assertEqual(store2.count(), 1)
        hits = store2.search("可持续相关内容", top_k=5)
        self.assertEqual(hits[0].page_content, "可持续相关内容")


if __name__ == "__main__":
    unittest.main()