"""DocumentService 单测：真实管线的保存/入库/清除/事件编排（FakeVector 免外部依赖）。"""

import os
import shutil
import tempfile
import unittest

from infra.adapters.storage import SqliteRepo
from modules.document.service import DocumentService
from modules.document.storage_service import StorageService
from modules.history import HistoryService


class FakeVector:
    """最小向量库替身：记录来源与其 chunk 产物目录。"""

    def __init__(self):
        self._sources: dict[str, set] = {}
        self.added: list = []

    def add_documents(self, documents, partition=None):
        self.added.append((partition, list(documents)))

    def store_documents_from_dir(self, directory, partition=None):
        source = os.path.basename(directory)
        self._sources.setdefault(partition, set()).add(source)
        chunk = os.path.join(os.path.dirname(directory), "chunk_out", os.path.splitext(source)[0])
        os.makedirs(os.path.join(chunk, "images"), exist_ok=True)

    def get_sources_by_partition(self, partition=None):
        return sorted(self._sources.get(partition, set()))

    def delete_by_sources(self, sources, *, partition=None):
        bucket = self._sources.get(partition, set())
        for s in sources:
            bucket.discard(os.path.basename(s))

    def delete_by_partition(self, partition=None):
        self._sources.pop(partition, None)

    def count(self):
        return len(self.added)

    def search(self, query, top_k=10, *, partition=None, source_filter=None):
        return []


class DocumentServiceTest(unittest.TestCase):
    def setUp(self):
        self.data_dir = tempfile.mkdtemp()
        self.vector = FakeVector()
        self.history = HistoryService(SqliteRepo("sqlite:///:memory:"))
        self.storage = StorageService(data_dir=self.data_dir, max_user_mb=0)
        self.svc = DocumentService(self.vector, self.history, self.storage, data_dir=self.data_dir)

    def tearDown(self):
        shutil.rmtree(self.data_dir, ignore_errors=True)

    def _upload_dir(self, user="alice"):
        return os.path.join(self.data_dir, "uploads", user)

    def test_upload_saves_indexes_and_writes_artifacts(self):
        res = self.svc.upload("Alice", "report.pdf", b"%PDF-fake")

        self.assertEqual(res.filename, "report.pdf")
        self.assertTrue(os.path.isfile(os.path.join(self._upload_dir(), "report.pdf")))
        self.assertEqual(self.vector.get_sources_by_partition("alice"), ["report.pdf"])
        self.assertTrue(os.path.isdir(os.path.join(self._upload_dir(), "chunk_out", "report")))

    def test_save_uploads_records_event(self):
        self.svc.save_uploads(
            "alice",
            [("a.pdf", b"%PDF", "application/pdf"), ("b.pdf", b"%PDF", "application/pdf")],
            session_id="s1",
        )
        hist = self.history.get_session_history("s1")
        self.assertTrue(any(h.get("type") == "event" and h.get("event_type") == "upload"
                            and set(h.get("files", [])) == {"a.pdf", "b.pdf"} for h in hist))

    def test_clear_sources_removes_vectors_files_and_artifacts(self):
        self.svc.upload("alice", "a.pdf", b"%PDF")
        self.svc.clear_sources("alice", ["a.pdf"], session_id="s1")

        self.assertEqual(self.vector.get_sources_by_partition("alice"), [])
        self.assertFalse(os.path.exists(os.path.join(self._upload_dir(), "a.pdf")))
        self.assertFalse(os.path.exists(os.path.join(self._upload_dir(), "chunk_out", "a")))

    def test_clear_all_removes_user_dir(self):
        self.svc.upload("alice", "a.pdf", b"%PDF")
        self.svc.clear_all("alice", session_id="s1")

        self.assertEqual(self.vector.get_sources_by_partition("alice"), [])
        self.assertFalse(os.path.isdir(self._upload_dir()))

    def test_upload_overwrite_forgets_old_vectors(self):
        self.svc.upload("alice", "a.pdf", b"%PDF")
        self.svc.upload("alice", "a.pdf", b"%PDF-new")
        self.assertEqual(self.vector.get_sources_by_partition("alice"), ["a.pdf"])

    def test_add_directory_indexes_existing_path(self):
        os.makedirs(self._upload_dir(), exist_ok=True)
        target = os.path.join(self._upload_dir(), "x.pdf")
        with open(target, "wb") as f:
            f.write(b"%PDF")
        self.svc.index_path("alice", target)
        self.assertEqual(self.vector.get_sources_by_partition("alice"), ["x.pdf"])


if __name__ == "__main__":
    unittest.main()