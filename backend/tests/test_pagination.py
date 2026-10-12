"""分页测试：仓储层分页 ``paginate_query`` + 仓储 ``where`` 修饰符（contains/or/降序）。"""

import unittest

from core.pagination import paginate, paginate_query
from infra.adapters.storage import SqliteRepo
from modules.user.service import UserService


class PaginateQueryTest(unittest.TestCase):
    def setUp(self):
        self.repo = SqliteRepo("sqlite:///:memory:")
        svc = UserService(self.repo)
        for name in ("alice", "bob", "carol", "dave", "erin"):
            svc.insert_user(name, "pw")

    # ── paginate（内存切片） ──

    def test_paginate_all_when_size_zero(self):
        out = paginate(["a", "b", "c"], key="documents")
        self.assertEqual(out, {"total": 3, "page": 1, "page_size": 3, "documents": ["a", "b", "c"]})

    def test_paginate_slice_and_oob(self):
        self.assertEqual(paginate(list("abcde"), page=2, page_size=2, key="items")["items"], ["c", "d"])
        self.assertEqual(paginate(list("abcde"), page=9, page_size=2, key="items")["items"], [])

    # ── paginate_query（下推仓储） ──

    def test_query_paging(self):
        out = paginate_query(self.repo, "users", order_by="id", page=1, page_size=2, key="items")
        self.assertEqual(out["total"], 5)
        self.assertEqual(out["page_size"], 2)
        self.assertEqual([u.username for u in out["items"]], ["alice", "bob"])

    def test_query_last_page(self):
        out = paginate_query(self.repo, "users", order_by="id", page=3, page_size=2, key="items")
        self.assertEqual([u.username for u in out["items"]], ["erin"])

    def test_query_desc_order(self):
        out = paginate_query(self.repo, "users", order_by="-id", page=1, page_size=2, key="items")
        self.assertEqual([u.username for u in out["items"]], ["erin", "dave"])

    def test_query_where_equality(self):
        out = paginate_query(self.repo, "users", where={"username": "bob"}, key="items")
        self.assertEqual(out["total"], 1)
        self.assertEqual(out["items"][0].username, "bob")

    def test_query_where_icontains(self):
        out = paginate_query(self.repo, "users", where={"username__icontains": "AR"}, key="items")
        self.assertEqual([u.username for u in out["items"]], ["carol"])

    def test_query_where_or(self):
        where = {"__or__": [{"username__icontains": "bo"}, {"username__icontains": "da"}]}
        out = paginate_query(self.repo, "users", where=where, order_by="id", key="items")
        self.assertEqual([u.username for u in out["items"]], ["bob", "dave"])

    def test_query_serialize(self):
        out = paginate_query(
            self.repo, "users", order_by="id", page_size=1, key="items",
            serialize=lambda u: {"u": u.username},
        )
        self.assertEqual(out["items"], [{"u": "alice"}])


if __name__ == "__main__":
    unittest.main()
