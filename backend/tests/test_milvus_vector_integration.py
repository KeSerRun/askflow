"""MilvusVectorStore 集成测试（需 docker 中的 Milvus 在线，否则跳过）。

使用独立测试集合（用完删除），不污染生产 rag_chunks。
"""

import hashlib
import uuid
import unittest

from infra.adapters.vector import MilvusVectorStore
from core.models import Document

_URI = "http://127.0.0.1:19530"


def _milvus_available() -> bool:
    try:
        from pymilvus import connections, utility

        connections.connect("_probe", uri=_URI, timeout=5)
        utility.has_collection("_probe_unused", using="_probe")
        connections.disconnect("_probe")
        return True
    except Exception:
        return False


class FakeEmbedder:
    def __init__(self, dim: int = 256):
        self._dim = dim

    @property
    def dimension(self) -> int:
        return self._dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for t in texts:
            seed = hashlib.sha256(t.encode("utf-8")).digest()
            # 循环扩展至 dim 维（md5/sha256 摘要长度 < dim）
            raw = (seed * (self._dim // len(seed) + 1))[: self._dim]
            out.append([int(b) / 255.0 for b in raw])
        return out


@unittest.skipUnless(_milvus_available(), "Milvus 容器不可用（docker compose up -d）")
class MilvusVectorStoreIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.collection = f"test_chunks_{uuid.uuid4().hex[:8]}"
        cls.embedder = FakeEmbedder()
        cls.store = MilvusVectorStore(
            cls.embedder, uri=_URI, collection_name=cls.collection, default_top_k=10
        )

    @classmethod
    def tearDownClass(cls):
        from pymilvus import connections, utility

        try:
            utility.drop_collection(cls.collection, using="_rag")
        except Exception:
            pass
        try:
            connections.disconnect("_rag")
        except Exception:
            pass

    def _doc(self, content, source):
        return Document(page_content=content, metadata={"source": source})

    def test_add_search(self):
        self.store.add_documents([
            self._doc("苹果公司营收增长强劲", "苹果财报.pdf"),
            self._doc("特斯拉电动车业务", "特斯拉财报.pdf"),
        ])
        self.assertGreaterEqual(self.store.count(), 2)

        hits = self.store.search("苹果公司营收增长强劲", top_k=5)
        self.assertGreaterEqual(len(hits), 1)
        self.assertEqual(hits[0].page_content, "苹果公司营收增长强劲")

    def test_sources_and_delete(self):
        self.add_random()
        srcs = self.store.get_sources()
        self.assertIn("c.pdf", srcs)
        self.store.delete_by_sources(["c.pdf"])
        self.assertNotIn("c.pdf", self.store.get_sources())

    def add_random(self):
        self.store.add_documents([self._doc("随机内容-" + uuid.uuid4().hex, "c.pdf")])


if __name__ == "__main__":
    unittest.main()