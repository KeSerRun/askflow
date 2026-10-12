# locustfile.py
from locust import HttpUser, task

USER = "loadtest"
PASSWORD = "Test12345"

class ChatUser(HttpUser):
    token = None

    def on_start(self):
        r = self.client.post("/api/login", json={"username": USER, "password": PASSWORD})
        data = r.json()
        if "access_token" not in data:
            raise RuntimeError(f"登录失败 status={r.status_code} body={data}")
        self.token = data["access_token"]
        self.headers = {"Authorization": f"Bearer {self.token}"}

    @task(3)
    def list_sessions(self):
        # 会话列表接口（按实际路径，例如 /api/sessions/{username}）
        self.client.get(f"/api/sessions/{USER}", headers=self.headers)

    # @task(1)
    # def query(self):
    #     # SSE 问答：非流式读完整响应再计时；会真实调用 LLM
    #     with self.client.post("/api/query", json={
    #         "session_id": "stress-s", "question": "介绍一下激光设备", "stream": True,
    #     }, headers=self.headers, name="POST /api/query", stream=True, catch_response=True) as resp:
    #         if resp.status_code >= 400:
    #             resp.failure(f"status {resp.status_code}")
    #         else:
    #             resp.success()