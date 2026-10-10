"""LocalObjectStore 单元测试。

验证对象存取契约：roundtrip / 前缀枚举 / 删除 / 路径穿越防护。
"""

import os
import tempfile
import unittest

from infra.adapters.object import LocalObjectStore


class LocalObjectStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.store = LocalObjectStore(self.tmp)

    def tearDown(self):
        for root, _dirs, files in os.walk(self.tmp, topdown=False):
            for name in files:
                os.remove(os.path.join(root, name))
            for name in _dirs:
                os.rmdir(os.path.join(root, name))
        os.rmdir(self.tmp)

    def test_roundtrip(self):
        self.store.put_bytes("uploads/u/a.pdf", b"pdf-bytes", content_type="application/pdf")
        self.assertEqual(self.store.get_bytes("uploads/u/a.pdf"), b"pdf-bytes")
        self.assertTrue(self.store.exists("uploads/u/a.pdf"))

    def test_put_file_and_get_to_file(self):
        src = os.path.join(self.tmp, "src.bin")
        with open(src, "wb") as f:
            f.write(b"hello")
        self.store.put_file("chunks/u/demo/full.md", src)
        dst = os.path.join(self.tmp, "dst.bin")
        self.assertTrue(self.store.get_to_file("chunks/u/demo/full.md", dst))
        with open(dst, "rb") as f:
            self.assertEqual(f.read(), b"hello")

    def test_list_prefix(self):
        self.store.put_bytes("uploads/a/x.txt", b"1")
        self.store.put_bytes("uploads/a/y.txt", b"2")
        self.store.put_bytes("uploads/b/z.txt", b"3")
        keys = list(self.store.list_keys("uploads/a"))
        self.assertEqual(sorted(keys), ["uploads/a/x.txt", "uploads/a/y.txt"])
        self.assertEqual(len(list(self.store.list_keys())), 3)

    def test_delete(self):
        self.store.put_bytes("k.bin", b"x")
        self.assertTrue(self.store.delete("k.bin"))
        self.assertFalse(self.store.delete("k.bin"))
        self.assertIsNone(self.store.get_bytes("k.bin"))

    def test_missing_returns_none(self):
        self.assertIsNone(self.store.get_bytes("nope.bin"))
        self.assertFalse(self.store.exists("nope.bin"))

    def test_path_traversal_rejected(self):
        with self.assertRaises(ValueError):
            self.store.get_bytes("../escape.bin")
        with self.assertRaises(ValueError):
            self.store.put_bytes("../../etc/hosts", b"x")
        with self.assertRaises(ValueError):
            self.store.list_keys("a/../b")

    def test_empty_key_rejected(self):
        with self.assertRaises(ValueError):
            self.store.put_bytes("", b"x")


if __name__ == "__main__":
    unittest.main()