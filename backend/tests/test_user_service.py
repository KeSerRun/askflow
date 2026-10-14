"""UserService 领域 CRUD 单测（用户名规范化/唯一性/凭据/分页）。"""

import unittest

from infra.adapters.storage import SqliteRepo
from modules.user import UserService


class UserServiceTest(unittest.TestCase):
    def setUp(self):
        self.svc = UserService(SqliteRepo("sqlite:///:memory:"))

    def test_insert_and_verify(self):
        self.assertTrue(self.svc.insert_user("alice", "pw1"))
        self.assertFalse(self.svc.insert_user("alice", "pw2"))  # 重复
        info = self.svc.check_user_credentials("alice", "pw1")
        self.assertEqual(info["username"], "alice")
        self.assertIsNone(self.svc.check_user_credentials("alice", "wrong"))

    def test_username_preserves_case(self):
        self.svc.insert_user("Alice", "pw")
        self.assertIsNone(self.svc.check_user_credentials("ALICE", "pw"))   # 大小写敏感
        self.assertIsNotNone(self.svc.check_user_credentials("Alice", "pw"))

    def test_role_and_password_update(self):
        self.svc.insert_user("alice", "pw")
        self.assertTrue(self.svc.update_user_role("alice", "admin"))
        self.assertEqual(self.svc.check_user_credentials("alice", "pw")["role"], "admin")
        self.assertTrue(self.svc.update_user_password("alice", "newpw"))
        self.assertIsNotNone(self.svc.check_user_credentials("alice", "newpw"))

    def test_list_and_delete(self):
        self.svc.insert_user("alice", "pw")
        self.svc.insert_user("bob", "pw")
        page = self.svc.get_all_users(page=1, page_size=10)
        self.assertEqual(page["total"], 2)
        self.assertEqual(len(page["items"]), 2)
        self.assertTrue(self.svc.delete_user("alice"))
        self.assertFalse(self.svc.delete_user("alice"))


if __name__ == "__main__":
    unittest.main()
