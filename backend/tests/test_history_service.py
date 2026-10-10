"""HistoryService 领域 CRUD 单测（qa/turn/event/归档/覆盖）。"""

import unittest

from infra.adapters.storage import SqliteRepo
from modules.history import HistoryService


class HistoryServiceTest(unittest.TestCase):
    def setUp(self):
        self.svc = HistoryService(SqliteRepo("sqlite:///:memory:"))

    def test_insert_and_get_shapes(self):
        self.svc.insert_session_history("s1", "你好", "你好!")
        self.svc.insert_session_turn("s1", [{"role": "user", "content": "hi"}])
        self.svc.insert_session_event("s1", "upload", ["a.pdf"])
        hist = self.svc.get_session_history("s1")
        self.assertEqual([h["type"] for h in hist], ["qa", "turn", "event"])
        self.assertEqual(hist[0]["user"], "你好")
        self.assertEqual(hist[1]["messages"], [{"role": "user", "content": "hi"}])
        self.assertEqual(hist[2]["event_type"], "upload")
        self.assertEqual(hist[2]["files"], ["a.pdf"])

    def test_empty_session_returns_none(self):
        self.assertIsNone(self.svc.get_session_history("nope"))

    def test_delete(self):
        self.svc.insert_session_history("s1", "q", "a")
        self.assertTrue(self.svc.delete_session_history("s1"))
        self.assertIsNone(self.svc.get_session_history("s1"))
        self.assertFalse(self.svc.delete_session_history("s1"))

    def test_archive_idempotent(self):
        self.svc.insert_session_history("s1", "q", "a")
        self.assertTrue(self.svc.archive_history("s1"))
        self.assertFalse(self.svc.archive_history("s1"))  # 已有归档 → 跳过
        # 活跃历史仍在，归档不影响读取
        self.assertEqual(len(self.svc.get_session_history("s1")), 1)

    def test_replace(self):
        self.svc.insert_session_history("s1", "old", "old-a")
        self.assertTrue(self.svc.replace_session_history("s1", [
            {"type": "qa", "user": "new", "assistant": "new-a"},
        ]))
        hist = self.svc.get_session_history("s1")
        self.assertEqual(len(hist), 1)
        self.assertEqual(hist[0]["user"], "new")


if __name__ == "__main__":
    unittest.main()