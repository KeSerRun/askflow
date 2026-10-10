"""InMemoryCache 单元测试：读写/TTL/删除。"""

import time
import unittest

from infra.adapters.cache import InMemoryCache


class InMemoryCacheTest(unittest.TestCase):
    def setUp(self):
        self.cache = InMemoryCache()

    def test_set_get(self):
        self.cache.set("k", {"a": 1}, ttl=60)
        self.assertEqual(self.cache.get("k"), {"a": 1})

    def test_missing_returns_none(self):
        self.assertIsNone(self.cache.get("nope"))

    def test_delete(self):
        self.cache.set("k", "v", ttl=60)
        self.assertTrue(self.cache.delete("k"))
        self.assertFalse(self.cache.delete("k"))
        self.assertIsNone(self.cache.get("k"))

    def test_clear(self):
        self.cache.set("a", 1)
        self.cache.set("b", 2)
        self.cache.clear()
        self.assertIsNone(self.cache.get("a"))
        self.assertIsNone(self.cache.get("b"))

    def test_ttl_expiry(self):
        self.cache.set("k", "v", ttl=1)
        self.assertEqual(self.cache.get("k"), "v")
        time.sleep(1.1)
        self.assertIsNone(self.cache.get("k"))

    def test_ttl_zero_never_expires(self):
        self.cache.set("k", "v", ttl=0)
        time.sleep(0.05)
        self.assertEqual(self.cache.get("k"), "v")


if __name__ == "__main__":
    unittest.main()