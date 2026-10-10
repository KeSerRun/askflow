"""SQLite 存储 + 领域服务 集成测试（无需外部服务，用临时文件库）。"""

import shutil
import tempfile
import unittest

from infra.adapters.storage import SqliteRepo
from modules.history import HistoryService
from modules.session import SessionService
from modules.user import UserService


class SqlStorageIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.mkdtemp()
        cls.repo = SqliteRepo(f"sqlite:///{cls._tmp}/rag.db")
        cls.users = UserService(cls.repo)
        cls.history = HistoryService(cls.repo)
        cls.sessions = SessionService(cls.repo, cls.history)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._tmp, ignore_errors=True)

    def setUp(self):
        # 清理测试数据（保证幂等）
        for username in ("int_alice", "int_bob"):
            self.users.delete_user(username)
        for sid in ("int_s1", "int_arch_s1", "int_rep_s1"):
            self.sessions._repo.delete_where("sessions", {"session_id": sid})
            self.history.delete_session_history(sid)

    def test_user_flow(self):
        u = self.users
        self.assertTrue(u.insert_user("int_alice", "pw1"))
        self.assertFalse(u.insert_user("int_alice", "pw2"))  # 重复
        self.assertEqual(u.check_user_credentials("INT_alice", "pw1")["username"], "int_alice")
        self.assertIsNone(u.check_user_credentials("int_alice", "wrong"))
        self.assertTrue(u.update_user_role("int_alice", "admin"))
        self.assertTrue(u.update_user_password("int_alice", "newpw"))
        self.assertIsNotNone(u.check_user_credentials("int_alice", "newpw"))
        self.assertTrue(u.get_all_users(page=1, page_size=100)["total"] >= 1)

    def test_session_and_history(self):
        self.sessions.create("int_s1", "int_alice")
        self.assertTrue(self.history.insert_session_history("int_s1", "你好", "你好!"))
        self.assertTrue(self.history.insert_session_turn("int_s1", [{"role": "user", "content": "hi"}]))
        self.assertTrue(self.history.insert_session_event("int_s1", "upload", ["a.pdf"]))

        hist = self.history.get_session_history("int_s1")
        self.assertIsNotNone(hist)
        types = {h["type"] for h in hist}
        self.assertEqual(types, {"qa", "turn", "event"})

        sessions = self.sessions.list_sessions("int_alice")
        self.assertTrue(any(x["id"] == "int_s1" for x in sessions))

    def test_archive(self):
        sid = "int_arch_s1"
        self.sessions._repo.delete_where("sessions", {"session_id": sid})
        self.history.delete_session_history(sid)
        self.history.insert_session_history(sid, "q", "a")

        self.assertTrue(self.history.archive_history(sid, None))
        self.assertFalse(self.history.archive_history(sid, None))  # 再次归档 → 跳过
        self.assertTrue(self.history.delete_session_history(sid))

    def test_replace_session_history(self):
        sid = "int_rep_s1"
        self.history.delete_session_history(sid)
        self.history.insert_session_history(sid, "old", "old-a")

        self.assertTrue(self.history.replace_session_history(sid, [
            {"type": "qa", "user": "new", "assistant": "new-a"},
        ]))
        hist = self.history.get_session_history(sid)
        self.assertEqual(hist[0]["user"], "new")
        self.assertTrue(self.history.delete_session_history(sid))


if __name__ == "__main__":
    unittest.main()