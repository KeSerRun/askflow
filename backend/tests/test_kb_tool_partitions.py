"""知识库工具的跨分区读取测试（回归：曾写死 __system__ 导致知识库文档读不到）。"""

import unittest

from agent.tools import _common
from core.models import Document


class FakeStore:
    """最小对象存储替身：按键前缀列举。"""

    def __init__(self, keys: dict):
        self.keys = dict(keys)

    def list_keys(self, prefix: str = ""):
        return (k for k in sorted(self.keys) if k.startswith(prefix))

    def list_objects(self, prefix: str = ""):
        return [(k, len(v)) for k, v in sorted(self.keys.items()) if k.startswith(prefix)]

    def get_bytes(self, key):
        return self.keys.get(key)


class FakeCtx:
    def __init__(self, store):
        self.object_store = store
        self.partition = None
        self.session_id = ""


def _store_with(*parts_and_docs):
    keys = {}
    for part, doc, text in parts_and_docs:
        stem = doc.rsplit(".", 1)[0]
        keys[f"uploads/{part}/chunk_out/{stem}/{stem}.txt"] = text.encode()
        keys[f"uploads/{part}/chunk_out/{stem}/images/img_1.png"] = b"PNGDATA"
    return FakeStore(keys)


class KnownPartitionsTest(unittest.TestCase):
    def test_probes_child_dirs(self):
        store = _store_with(("产品手册", "a.pdf", "A"), ("kww", "b.pdf", "B"))
        parts = _common._known_partitions(store)
        self.assertEqual(sorted(parts), ["kww", "产品手册"])

    def test_system_partition_sorted_first(self):
        store = _store_with(("aaa", "a.pdf", "A"), ("__system__", "b.pdf", "B"))
        self.assertEqual(_common._known_partitions(store)[0], "__system__")

    def test_empty_store(self):
        self.assertEqual(_common._known_partitions(FakeStore({})), [])

    def test_none_store(self):
        self.assertEqual(_common._known_partitions(None), [])

    def test_candidates_falls_back_to_system(self):
        self.assertEqual(_common._partition_candidates(FakeStore({})), ["__system__"])

    def test_candidates_honors_explicit_partition(self):
        cands = _common._partition_candidates(_store_with(("kb", "a.pdf", "A")), "kb")
        self.assertEqual(cands, ["kb"])


class ReadSystemTextTest(unittest.TestCase):
    def test_reads_from_knowledge_base_partition(self):
        ctx = FakeCtx(_store_with(("产品手册", "报告.pdf", "正文内容")))
        self.assertEqual(_common._read_system_text(ctx, "报告.pdf"), "正文内容")

    def test_reads_when_partition_given(self):
        ctx = FakeCtx(_store_with(("库A", "r.pdf", "AAA"), ("库B", "x.pdf", "XXX")))
        self.assertEqual(_common._read_system_text(ctx, "r.pdf", "库A"), "AAA")

    def test_wrong_partition_returns_none(self):
        ctx = FakeCtx(_store_with(("库A", "r.pdf", "AAA")))
        self.assertIsNone(_common._read_system_text(ctx, "r.pdf", "库B"))

    def test_missing_doc_returns_none(self):
        ctx = FakeCtx(_store_with(("库A", "r.pdf", "AAA")))
        self.assertIsNone(_common._read_system_text(ctx, "不存在.pdf"))

    def test_no_store_returns_none(self):
        self.assertIsNone(_common._read_system_text(FakeCtx(None), "x.pdf"))


class ResolveImageBytesTest(unittest.TestCase):
    def test_resolves_via_chunk_image_key(self):
        store = _store_with(("产品手册", "报告.pdf", "x"))
        ctx = FakeCtx(store)
        key = "uploads/产品手册/chunk_out/报告/images/img_1.png"
        data = _common._resolve_image_bytes(ctx, f"/api/documents/chunk_image?key={key}")
        self.assertEqual(data, b"PNGDATA")

    def test_resolves_via_document_image_url(self):
        """旧式 /api/documents/image/{stem}/{img} 直链也要能跨分区解析。"""
        store = _store_with(("产品手册", "报告.pdf", "x"))
        ctx = FakeCtx(store)
        data = _common._resolve_image_bytes(ctx, "/api/documents/image/报告/images/img_1.png")
        self.assertEqual(data, b"PNGDATA")


class FormatChunkTest(unittest.TestCase):
    """检索结果片段头应展示所属知识库，而不是"系统文档/用户文档"。"""

    def _header(self, partition):
        doc = Document(page_content="正文", metadata={"partition": partition, "source": "a.pdf"})
        return _common._format_chunk(1, doc).splitlines()[0]

    def test_shows_knowledge_base_name(self):
        self.assertIn("产品手册", self._header("产品手册"))
        self.assertNotIn("系统文档", self._header("产品手册"))
        self.assertNotIn("用户文档", self._header("产品手册"))

    def test_system_partition_not_labelled(self):
        head = self._header("__system__")
        self.assertNotIn("系统文档", head)
        self.assertNotIn("用户文档", head)

    def test_image_url_carries_partition(self):
        doc = Document(page_content="", metadata={
            "partition": "产品手册", "source": "a.pdf",
            "chunk_type": "image", "img_path": "images/i.png",
        })
        out = _common._format_chunk(1, doc)
        self.assertIn("partition=%E4%BA%A7%E5%93%81%E6%89%8B%E5%86%8C", out)  # 产品手册


if __name__ == "__main__":
    unittest.main()
