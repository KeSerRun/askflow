"""SessionService 单测：会话预览（应用层）与归属校验。"""

import unittest

from infra.adapters.storage import SqliteRepo
from modules.history import HistoryService
from modules.session import SessionService
from modules.user import UserService


class SessionServiceTest(unittest.TestCase):
    def setUp(self):
        self.repo = SqliteRepo("sqlite:///:memory:")
        self.history = HistoryService(self.repo)
        self.users = UserService(self.repo)
        self.svc = SessionService(self.repo, self.history)
        self.users.insert_user("bob", "pw")
