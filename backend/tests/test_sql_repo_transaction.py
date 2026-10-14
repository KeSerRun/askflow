"""SqliteRepo 显式事务测试（sqlite 内存库，无需任何外部服务）。

覆盖：事务提交 / 事务回滚 / 单方法自带事务（回归）。
"""

import unittest

from infra.adapters.storage import SqliteRepo
from modules.user.entity import User


def _user(username: str, role: str = "user") -> User:
    return User(username=username, password="p", role=role, created_at="t")


class SqliteRepoTransactionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = SqliteRepo("sqlite:///:memory:")

    def test_single_insert_auto_commits(self):
        """不带 session：一方法一事务，立即落库。"""
        uid = self.repo.insert("users", _user("tx_single"))
        self.assertIsNotNone(uid)
        self.assertEqual(self.repo.get("users", uid).username, "tx_single")

    def test_transaction_commits_all(self):
        """一个事务内多次写，正常退出全部提交。"""
        with self.repo.transaction() as s:
            uid = self.repo.insert("users", _user("tx_commit_a"), session=s)
            ok = self.repo.update("users", uid, {"role": "admin"}, session=s)
            self.repo.insert("users", _user("tx_commit_b"), session=s)
        self.assertTrue(ok)
        self.assertEqual(self.repo.get("users", uid).role, "admin")
        self.assertIsNotNone(self.repo.find("users", {"username": "tx_commit_b"}))

    def test_transaction_rolls_back_on_error(self):
        """抛异常 → 整个事务回滚，已插入的行不落库。"""
        before = self.repo.count("users")
        with self.assertRaises(RuntimeError):
            with self.repo.transaction() as s:
                self.repo.insert("users", _user("tx_rollback"), session=s)
                raise RuntimeError("force rollback")
        self.assertEqual(self.repo.count("users"), before)
        self.assertEqual(self.repo.find("users", {"username": "tx_rollback"}), [])

    def test_transaction_visibility_inside(self):
        """事务内可看到自己未提交的写入（同 session）。"""
        with self.repo.transaction() as s:
            uid = self.repo.insert("users", _user("tx_visible"), session=s)
            self.assertIsNotNone(self.repo.get("users", uid, session=s))


if __name__ == "__main__":
    unittest.main()
