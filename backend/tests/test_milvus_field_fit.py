"""MilvusVectorStore 写入前字段裁剪 + 二分重试的单元测试（不连真实 Milvus）。"""

import unittest
from unittest.mock import MagicMock

from core.models import Document
from infra.adapters.vector.milvus import MilvusVectorStore


class _Embedder:
    dimension = 8

    def embed(self, texts, batch_size: int = 32):
        return [[0.1] * 8 for _ in texts]

    def embed_image(self, data: bytes):
        return [0.1] * 8


def _store() -> MilvusVectorStore:
    s = MilvusVectorStore(_Embedder(), uri="http://127.0.0.1:19530")
    # 直接注入已建好的假客户端，跳过懒连接
    s._client_cached = MagicMock()
    return s


class FieldFitTest(unittest.TestCase):
    """Milvus 的 VARCHAR max_length 按 **UTF-8 字节** 校验，故断言字节长度。"""

    def test_short_value_unchanged(self):
        self.assertEqual(MilvusVectorStore._fit("abc", 10, "f"), "abc")

    def test_exact_limit_unchanged(self):
        self.assertEqual(MilvusVectorStore._fit("x" * 10, 10, "f"), "x" * 10)

    def test_over_limit_truncated_within_byte_budget(self):
        out = MilvusVectorStore._fit("y" * 5000, 1024, "caption")
        self.assertLessEqual(len(out.encode("utf-8")), 1024)
        self.assertTrue(out.endswith("…"))

    def test_multibyte_truncated_by_bytes_not_chars(self):
        """回归：中文按字符截会超字节限（曾报 code=1100 length=514 max=512）。"""
        out = MilvusVectorStore._fit("中" * 900, 512, "source")
        self.assertLessEqual(len(out.encode("utf-8")), 512)
        self.assertGreater(len(out), 0)

    def test_ascii_limit_boundary(self):
        out = MilvusVectorStore._fit("s" * 900, 512, "source")
        self.assertLessEqual(len(out.encode("utf-8")), 512)

    def test_tiny_limit_still_respects_bytes(self):
        for limit in (1, 2, 3, 4, 5):
            out = MilvusVectorStore._fit("中文abc", limit, "f")
            self.assertLessEqual(len(out.encode("utf-8")), limit, f"limit={limit}")

    def test_none_becomes_empty(self):
        self.assertEqual(MilvusVectorStore._fit(None, 10, "f"), "")

    def test_empty_string(self):
        self.assertEqual(MilvusVectorStore._fit("", 10, "f"), "")


class LimitsConsistencyTest(unittest.TestCase):
    def test_limits_cover_all_varchar_fields(self):
        """裁剪上限必须覆盖 schema 里的全部 VARCHAR 字段。"""
        self.assertEqual(
            set(MilvusVectorStore._VARCHAR_LIMITS),
            {"doc_id", "text", "source", "partition", "chunk_type",
             "img_path", "caption", "footnote", "parent_id", "timestamp"},
        )

    def test_doc_id_and_parent_id_fit_md5_hex(self):
        # md5 hexdigest 长度 32，必须容得下
        self.assertGreaterEqual(MilvusVectorStore._VARCHAR_LIMITS["doc_id"], 32)
        self.assertGreaterEqual(MilvusVectorStore._VARCHAR_LIMITS["parent_id"], 32)


class AddDocumentsTest(unittest.TestCase):
    def _add(self, docs):
        s = _store()
        s.add_documents(docs)
        return s

    def test_overlong_caption_is_truncated_before_insert(self):
        """回归：caption 超 VARCHAR(1024) 曾导致整批 insert 失败（code=1100）。"""
        doc = Document(
            page_content="图注",
            metadata={
                "chunk_type": "text", "source": "a.pdf", "partition": "kb",
                "caption": "长" * 5000, "img_data": b"\x89PNG-fake",
                "img_path": "images/img_1.png",
            },
        )
        s = self._add([doc])
        rows = s._client_cached.insert.call_args[0][1]
        self.assertLessEqual(len(rows[0]["caption"].encode("utf-8")), 1024)

    def test_overlong_source_and_partition_truncated(self):
        doc = Document(
            page_content="正文",
            metadata={"chunk_type": "text", "source": "s" * 900, "partition": "p" * 400},
        )
        s = self._add([doc])
        rows = s._client_cached.insert.call_args[0][1]
        self.assertLessEqual(len(rows[0]["source"].encode("utf-8")), 512)
        self.assertLessEqual(len(rows[0]["partition"].encode("utf-8")), 128)

    def test_all_string_fields_within_byte_limits(self):
        """所有 VARCHAR 字段写入前必须都在字节上限内。"""
        doc = Document(
            page_content="正文",
            metadata={
                "chunk_type": "text", "source": "文" * 900, "partition": "库" * 400,
                "footnote": "脚" * 90000, "parent_id": "p" * 200,
                "timestamp": "t" * 200, "caption": "c" * 5000,
            },
        )
        s = self._add([doc])
        rows = s._client_cached.insert.call_args[0][1]
        limits = MilvusVectorStore._VARCHAR_LIMITS
        for field, limit in limits.items():
            val = rows[0].get(field)
            if isinstance(val, str):
                self.assertLessEqual(len(val.encode("utf-8")), limit, f"字段 {field} 仍超限")

    def test_partition_defaults_to_system(self):
        doc = Document(page_content="正文", metadata={"chunk_type": "text"})
        s = self._add([doc])
        rows = s._client_cached.insert.call_args[0][1]
        self.assertEqual(rows[0]["partition"], "__system__")

    def test_table_chunks_skipped(self):
        doc = Document(page_content="表格", metadata={"chunk_type": "table"})
        s = self._add([doc])
        s._client_cached.insert.assert_not_called()

    def test_image_without_bytes_skipped(self):
        doc = Document(page_content="c", metadata={"chunk_type": "image", "img_path": "a.png"})
        s = self._add([doc])
        s._client_cached.insert.assert_not_called()


class BinarySplitRetryTest(unittest.TestCase):
    """整批失败时二分重试，避免个别坏行拖垮整篇文档。"""

    def test_batch_failure_splits_until_bad_row_found(self):
        s = _store()
        good1 = {"doc_id": "a" * 32}
        bad = {"doc_id": "b" * 32}
        good2 = {"doc_id": "c" * 32}
        good3 = {"doc_id": "d" * 32}

        calls: list[int] = []

        def insert(_name, rows):
            calls.append(len(rows))
            if any(r["doc_id"] == bad["doc_id"] for r in rows):
                raise ValueError("code=1100 varchar too long")

        s._client_cached.insert.side_effect = insert
        s._insert_rows([good1, bad, good2, good3])

        # 应发生二分：4 → 2+2 → 单行…
        self.assertGreater(len(calls), 1)
        self.assertIn(1, calls)

    def test_single_bad_row_is_skipped_not_raised(self):
        s = _store()
        s._client_cached.insert.side_effect = ValueError("code=1100")
        s._insert_rows([{"doc_id": "x" * 32}])   # 不抛异常

    def test_success_path_inserts_once(self):
        s = _store()
        s._insert_rows([{"doc_id": "a" * 32}, {"doc_id": "b" * 32}])
        self.assertEqual(s._client_cached.insert.call_count, 1)
        self.assertEqual(s._client_cached.flush.call_count, 1)


if __name__ == "__main__":
    unittest.main()
