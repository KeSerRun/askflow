"""DocumentService 单测：会话附件暂存 + 系统文档入库（FakeVector 免外部依赖）。"""

import os
import shutil
import tempfile
import unittest

from fake_object_store import LocalDirObjectStore

from core.app_errors import QuotaExceeded
from modules.document.service import DocumentService


class FakeVector:
    """最小向量库替身：记录来源与其 chunk 产物目录（仅实现被测代码会用到的接口）。"""

    def __init__(self):
        self._sources: set = set()
        self.deleted: list[tuple] = []      # (sources, partition)

    def store_documents_from_dir(self, directory, partition):
        source = os.path.basename(directory)
        self._sources.add(source)
        chunk = os.path.join(os.path.dirname(directory), "chunk_out", os.path.splitext(source)[0])
        os.makedirs(os.path.join(chunk, "images"), exist_ok=True)

    def get_sources(self):
        return sorted(self._sources)

    def delete_by_sources(self, sources, partition=None):
        self.deleted.append((list(sources), partition))
        for s in sources:
            self._sources.discard(os.path.basename(s))


class DocumentServiceTest(unittest.TestCase):
    def setUp(self):
        self.data_dir = tempfile.mkdtemp()
        self.vector = FakeVector()
        self.svc = DocumentService(
            self.vector,
            object_store=LocalDirObjectStore(self.data_dir),
            max_session_mb=1,  # 会话上限 1MB 便于测试
        )

    def tearDown(self):
        shutil.rmtree(self.data_dir, ignore_errors=True)

    def _upload_dir(self, user="__system__"):
        return os.path.join(self.data_dir, "uploads", user)

    def _session_dir(self, user="alice", sid="s1"):
        return os.path.join(self.data_dir, "sessions", user, sid)

    # ── 系统文档入库（管理端路径） ──

    def test_upload_saves_indexes_and_writes_artifacts(self):
        res = self.svc.upload("__system__", "report.pdf", b"%PDF-fake")

        self.assertEqual(res.filename, "report.pdf")
        self.assertTrue(os.path.isfile(os.path.join(self._upload_dir(), "report.pdf")))
        self.assertEqual(self.vector.get_sources(), ["report.pdf"])
        self.assertTrue(os.path.isdir(os.path.join(self._upload_dir(), "chunk_out", "report")))

    def test_upload_overwrite_forgets_old_vectors(self):
        self.svc.upload("__system__", "a.pdf", b"%PDF")
        self.svc.upload("__system__", "a.pdf", b"%PDF-new")
        self.assertEqual(self.vector.get_sources(), ["a.pdf"])

    def test_forget_source_scoped_to_partition(self):
        """回归：删向量必须带 partition —— 否则同名文件会跨知识库误删。

        场景：库A 与 库B 都有 report.pdf，在 库A 重传时应只清 库A 的向量。
        """
        self.svc.forget_source("库A", "report.pdf")
        self.assertEqual(self.vector.deleted, [(["report.pdf"], "库A")])

    def test_upload_overwrite_only_touches_its_own_kb(self):
        """重传同库文件时，删向量必须限定在该库（purge 只删文件、不动向量）。"""
        self.svc.upload("库A", "same.pdf", b"%PDF")
        self.vector.deleted.clear()
        self.svc.upload("库A", "same.pdf", b"%PDF-2")
        self.assertEqual([p for _, p in self.vector.deleted], ["库A"])
        self.assertEqual(self.vector.deleted, [(["same.pdf"], "库A")])

    # ── MinerU 解析图片读取（回归：曾写死 __system__ 导致知识库文档图片 404） ──

    def test_read_image_from_knowledge_base_partition(self):
        """文档视图图片按 partition 读取（文档归属知识库后不再是 __system__）。"""
        key = "uploads/产品手册/chunk_out/report/images/img_1.png"
        self.svc._files.put(key, b"\x89PNG-fake-bytes")

        found = self.svc.read_image("report", "img_1.png", "产品手册")
        self.assertIsNotNone(found, "应能在知识库分区下找到图片")
        data, media, name = found
        self.assertEqual(data, b"\x89PNG-fake-bytes")
        self.assertEqual(media, "image/png")
        self.assertEqual(name, "img_1.png")

    def test_read_image_accepts_images_prefix(self):
        self.svc._files.put(
            "uploads/库B/chunk_out/doc/images/img_2.jpg", b"JPEGDATA")
        found = self.svc.read_image("doc", "images/img_2.jpg", "库B")
        self.assertIsNotNone(found)
        self.assertEqual(found[0], b"JPEGDATA")

    def test_read_image_wrong_partition_not_leaked(self):
        """图片隔离：指定别的知识库不应命中。"""
        self.svc._files.put(
            "uploads/库A/chunk_out/doc/images/img_3.png", b"AAA")
        self.assertIsNone(self.svc.read_image("doc", "img_3.png", "库B"))

    def test_read_image_without_partition_probes_known_parts(self):
        """未指定 partition 时自动探测已有分区（历史 /documents/image/... 直链仍可用）。"""
        self.svc._files.put(
            "uploads/库C/chunk_out/doc/images/img_4.png", b"CCC")
        found = self.svc.read_image("doc", "img_4.png")
        self.assertIsNotNone(found)
        self.assertEqual(found[0], b"CCC")

    def test_read_image_global_finds_across_partitions(self):
        self.svc._files.put(
            "uploads/库D/chunk_out/doc/images/img_5.png", b"DDD")
        found = self.svc.read_image_global("img_5.png")
        self.assertIsNotNone(found)
        self.assertEqual(found[0], b"DDD")

    # ── 上传校验 ──

    def test_session_stage_only_writes_no_vector(self):
        saved = self.svc.save_session_files(
            "alice", "s1", [("a.pdf", b"%PDF", "application/pdf")],
        )
        self.assertEqual(saved[0]["filename"], "a.pdf")
        self.assertTrue(os.path.isfile(os.path.join(self._session_dir(), "a.pdf")))
        # 关键：不进向量库、无 chunk 产物
        self.assertEqual(self.vector.get_sources(), [])
        self.assertFalse(os.path.isdir(os.path.join(self._session_dir(), "chunk_out")))

    def test_session_quota_enforced(self):
        big = b"x" * (2 * 1024 * 1024)  # 2MB > 1MB 上限
        with self.assertRaises(QuotaExceeded):
            self.svc.save_session_files("alice", "s1", [("big.bin", big, "application/octet-stream")])

    def test_session_isolation_between_sessions(self):
        self.svc.save_session_files("alice", "s1", [("a.txt", b"a", "text/plain")])
        self.svc.save_session_files("alice", "s2", [("b.txt", b"b", "text/plain")])
        self.assertEqual([f["name"] for f in self.svc.list_session_files("alice", "s1")], ["a.txt"])
        self.assertEqual([f["name"] for f in self.svc.list_session_files("alice", "s2")], ["b.txt"])

    def test_session_delete_and_clear(self):
        self.svc.save_session_files("alice", "s1", [
            ("a.txt", b"a", "text/plain"), ("b.txt", b"b", "text/plain"),
        ])
        self.svc.delete_session_file("alice", "s1", "a.txt")
        self.assertEqual([f["name"] for f in self.svc.list_session_files("alice", "s1")], ["b.txt"])
        self.svc.clear_session_files("alice", "s1")
        self.assertEqual(self.svc.list_session_files("alice", "s1"), [])

    def test_session_usage_reports_limit(self):
        self.svc.save_session_files("alice", "s1", [("a.txt", b"a", "text/plain")])
        usage = self.svc.session_usage("alice", "s1")
        self.assertEqual(usage["max_mb"], 1)
        self.assertTrue(usage["limit_enabled"])


if __name__ == "__main__":
    unittest.main()
