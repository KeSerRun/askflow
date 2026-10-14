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

    def store_documents_from_dir(self, directory):
        source = os.path.basename(directory)
        self._sources.add(source)
        chunk = os.path.join(os.path.dirname(directory), "chunk_out", os.path.splitext(source)[0])
        os.makedirs(os.path.join(chunk, "images"), exist_ok=True)

    def get_sources(self):
        return sorted(self._sources)

    def delete_by_sources(self, sources):
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

    # ── 会话附件暂存（只落盘，不解析/不入库） ──

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
