"""AuthService 单测：规范化/唯一性/凭据/双令牌签发与 refresh 轮换，不依赖 HTTP 与真实存储。"""

import unittest

from core.app_errors import InvalidCredentials, InvalidRefreshToken, UsernameAlreadyExists
from modules.auth import AuthService


class _FakeUsers:
    """最小用户存储替身（鸭子类型，仅实现 AuthService 用到的两个方法）。"""

    def __init__(self):
        self._rows = {}

    def insert_user(self, username, password, role="user"):
        if username in self._rows:
            return False
        self._rows[username] = {"username": username, "password": password, "role": role}
        return True

    def check_user_credentials(self, username, password):
        row = self._rows.get(username)
        if row and row["password"] == password:
            return {"username": row["username"], "role": row["role"]}
        return None


class AuthServiceTest(unittest.TestCase):
    def setUp(self):
        self.service = AuthService(_FakeUsers(), jwt_secret="unit-test-secret")

    def test_register_preserves_case(self):
        self.service.register("  Alice ", "pw")
        with self.assertRaises(InvalidCredentials):
            self.service.login("ALICE", "pw")          # 大小写敏感
        user = self.service.login("Alice", "pw")       # 精确匹配
        self.assertEqual(user.username, "Alice")

    def test_register_duplicate_raises(self):
        self.service.register("alice", "pw")
        with self.assertRaises(UsernameAlreadyExists):
            self.service.register("alice", "pw2")

    def test_login_invalid_credentials_raises(self):
        self.service.register("alice", "pw")
        with self.assertRaises(InvalidCredentials):
            self.service.login("alice", "wrong")

    def test_login_returns_access_and_refresh(self):
        import jwt

        self.service.register("alice", "pw")
        user = self.service.login("alice", "pw")
        self.assertEqual(user.role, "user")
        # access 是带 exp 与 type=access 的 JWT
        payload = jwt.decode(user.access_token, "unit-test-secret", algorithms=["HS256"])
        self.assertEqual(payload["username"], "alice")
        self.assertEqual(payload["role"], "user")
        self.assertEqual(payload["type"], "access")
        self.assertIn("exp", payload)
        # refresh 是非 JWT 的不透明随机串
        self.assertNotIn(".", user.refresh_token)

    def test_refresh_rotates_token(self):
        self.service.register("alice", "pw")
        first = self.service.login("alice", "pw")
        second = self.service.refresh(first.refresh_token)
        # refresh 令牌已轮换
        self.assertNotEqual(second.refresh_token, first.refresh_token)
        # 旧 refresh 已轮换失效
        with self.assertRaises(InvalidRefreshToken):
            self.service.refresh(first.refresh_token)
        # 新 refresh 可用
        self.service.refresh(second.refresh_token)

    def test_refresh_invalid_token_raises(self):
        self.service.register("alice", "pw")
        self.service.login("alice", "pw")
        with self.assertRaises(InvalidRefreshToken):
            self.service.refresh("totally-bogus-token")

    def test_logout_revokes_all_sessions(self):
        self.service.register("alice", "pw")
        dev_a = self.service.login("alice", "pw")
        dev_b = self.service.login("alice", "pw")
        # 吊销一个 → 该用户全部 refresh 失效
        self.assertEqual(self.service.logout(dev_a.refresh_token), 2)
        with self.assertRaises(InvalidRefreshToken):
            self.service.refresh(dev_a.refresh_token)
        with self.assertRaises(InvalidRefreshToken):
            self.service.refresh(dev_b.refresh_token)

    def test_register_preserves_role_default(self):
        self.service.register("bob", "pw")
        self.assertEqual(self.service.login("bob", "pw").role, "user")


if __name__ == "__main__":
    unittest.main()