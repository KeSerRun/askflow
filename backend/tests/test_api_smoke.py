"""统一 API 冒烟：关键路由注册 + health（不触发真实 LLM/MinerU 调用）。

统一 API（单套 /api，不分 v1/v2）：验证路由面完整、无并行版本残留。
"""

import unittest

import jwt
from fastapi.testclient import TestClient

from app import app
from config import conf


def _admin_headers() -> dict:
    token = jwt.encode(
        {"username": "admin", "role": "admin", "type": "access"},
        conf.auth_jwt_secret, algorithm="HS256"
    )
    return {"Authorization": f"Bearer {token}"}


class ApiSmokeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # with 触发 lifespan（构建本地容器：加载向量/客户端，无网络请求）
        with TestClient(app) as c:
            cls.paths = set(c.get("/openapi.json").json()["paths"].keys())
            cls.health_status = c.get("/api/health").status_code

    def test_health_ok(self):
        self.assertEqual(self.health_status, 200)

    def test_core_routes_registered(self):
        expected = [
            "/api/health",
            "/api/login",
            "/api/register",
            "/api/styles",
            "/api/query",
            "/api/query/cancel",
            "/api/session_files",
            "/api/session_files/upload",
        ]
        for route in expected:
            self.assertIn(route, self.paths, f"missing {route}")

    def test_admin_routes_present(self):
        admin = [p for p in self.paths if p.startswith("/api/admin")]
        self.assertGreaterEqual(len(admin), 5)

    def test_restart_route_registered(self):
        # 仅校验路由存在；不调用（否则会真的重启进程）
        self.assertIn("/api/admin/restart", self.paths)
        self.assertIn("/api/admin/config", self.paths)

    def test_no_versioned_parallel_routes(self):
        v2 = [p for p in self.paths if "/api/v2" in p]
        self.assertEqual(v2, [], "并行版本路由（/api/v2）应已合并进统一 /api")

    def test_register_validation_returns_string_detail(self):
        """Pydantic 校验失败应为 400 且 detail 为字符串（前端直接展示）。"""
        with TestClient(app) as c:
            resp = c.post("/api/register", json={"username": "someone"})
        self.assertEqual(resp.status_code, 400)
        self.assertIsInstance(resp.json()["detail"], str)

    def test_query_requires_question(self):
        with TestClient(app) as c:
            resp = c.post("/api/query", headers=_admin_headers(), json={"session_id": "s1"})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("question", resp.json()["detail"])

    def test_admin_create_user_validates_password(self):
        with TestClient(app) as c:
            resp = c.post(
                "/api/admin/users",
                headers=_admin_headers(),
                json={"username": "abc", "password": "123"},
            )
        self.assertEqual(resp.status_code, 400)
        self.assertIsInstance(resp.json()["detail"], str)


if __name__ == "__main__":
    unittest.main()
