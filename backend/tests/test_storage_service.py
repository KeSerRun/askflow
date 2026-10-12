"""StorageService 单测：目录配额判定与目录统计。"""

import os
import shutil
import tempfile
import unittest

from core.app_errors import QuotaExceeded
from modules.document.service import StorageService


class StorageServiceTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.svc = StorageService()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _write(self, name, nbytes):
        with open(os.path.join(self.dir, name), "wb") as f:
            f.write(b"x" * nbytes)

    def test_unlimited_when_max_zero(self):
        self._write("a.bin", 3 * 1024 * 1024)
        ok, _, max_mb = self.svc.check(self.dir, 0)
        self.assertTrue(ok)
        self.assertEqual(max_mb, 0)

    def test_under_limit(self):
        self._write("a.bin", 512 * 1024)
        ok, cur, max_mb = self.svc.check(self.dir, 1)
        self.assertTrue(ok)
        self.assertLess(cur, 1)
        self.assertEqual(max_mb, 1)

    def test_over_limit(self):
        self._write("a.bin", 2 * 1024 * 1024)  # 2MB > 1MB
        ok, _, max_mb = self.svc.check(self.dir, 1)
        self.assertFalse(ok)
        self.assertEqual(max_mb, 1)

    def test_additional_bytes_counted(self):
        self._write("a.bin", 512 * 1024)
        ok, _, _ = self.svc.check(self.dir, 1, additional_bytes=1024 * 1024)
        self.assertFalse(ok)

    def test_enforce_raises(self):
        self._write("a.bin", 2 * 1024 * 1024)
        with self.assertRaises(QuotaExceeded):
            self.svc.enforce(self.dir, 1)

    def test_usage_reports_limit(self):
        self._write("a.bin", 1024)
        usage = self.svc.usage(self.dir, 1)
        self.assertEqual(usage["max_mb"], 1)
        self.assertTrue(usage["limit_enabled"])
        self.assertTrue(usage["ok"])

    def test_dir_size_bytes_missing_dir(self):
        self.assertEqual(self.svc.dir_size_bytes(os.path.join(self.dir, "nope")), 0)


if __name__ == "__main__":
    unittest.main()
