"""StorageService 单测：配额判定与目录统计。"""

import os
import shutil
import tempfile
import unittest

from modules.document.storage_service import StorageService


class StorageServiceTest(unittest.TestCase):
    def setUp(self):
        self.data_dir = tempfile.mkdtemp()
        self.upload_dir = os.path.join(self.data_dir, "uploads", "alice")
        os.makedirs(self.upload_dir, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.data_dir, ignore_errors=True)

    def _write(self, name: str, size: int):
        with open(os.path.join(self.upload_dir, name), "wb") as f:
            f.write(b"x" * size)

    def test_admin_unlimited(self):
        svc = StorageService(data_dir=self.data_dir, max_user_mb=1)
        ok, current, max_mb = svc.check("alice", "admin")
        self.assertTrue(ok)
        self.assertEqual(current, 0)

    def test_disabled_limit(self):
        svc = StorageService(data_dir=self.data_dir, max_user_mb=0)
        ok, _, max_mb = svc.check("alice", "user")
        self.assertTrue(ok)
        self.assertEqual(max_mb, 0)

    def test_under_limit(self):
        self._write("a.pdf", 300 * 1024)
        svc = StorageService(data_dir=self.data_dir, max_user_mb=1)  # 1 MB
        ok, current, max_mb = svc.check("alice", "user")
        self.assertTrue(ok)
        self.assertGreater(current, 0)
        self.assertEqual(max_mb, 1)

    def test_over_limit_with_additional_bytes(self):
        svc = StorageService(data_dir=self.data_dir, max_user_mb=1)
        ok, current, max_mb = svc.check("alice", "user", additional_bytes=2 * 1024 * 1024)
        self.assertFalse(ok)
        self.assertGreaterEqual(current, max_mb)

    def test_only_counts_files_not_dirs(self):
        os.makedirs(os.path.join(self.upload_dir, "chunk_out"), exist_ok=True)
        svc = StorageService(data_dir=self.data_dir, max_user_mb=1)
        ok, current, _ = svc.check("alice", "user")
        self.assertTrue(ok)
        self.assertEqual(current, 0)


if __name__ == "__main__":
    unittest.main()