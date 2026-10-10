"""RabbitMQTaskQueue 集成测试（需 docker 中的 RabbitMQ 在线，否则跳过）。

独立队列名避免与生产冲突；任务状态存进程内 Cache。
"""

import time
import unittest
import uuid

from infra.adapters.cache import InMemoryCache
from infra.adapters.queue import RabbitMQTaskQueue

_URL = "amqp://askflow:askflow_password@127.0.0.1:5672/"


def _mq_available() -> bool:
    try:
        import pika

        conn = pika.BlockingConnection(pika.URLParameters(_URL))
        conn.close()
        return True
    except Exception:
        return False


@unittest.skipUnless(_mq_available(), "RabbitMQ 容器不可用（docker compose up -d）")
class RabbitMQTaskQueueIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.queue_name = f"test_{uuid.uuid4().hex[:8]}"
        self.cache = InMemoryCache()
        self.queue = RabbitMQTaskQueue(
            _URL, queue=self.queue_name, status_store=self.cache, consumers=2
        )
        self.queue.register_handler("sum", lambda p: {"total": sum(p["items"])})

    def tearDown(self):
        self.queue.shutdown()

    def test_enqueue_consume_and_status(self):
        self.queue.start_consumers()
        task_id = self.queue.enqueue("sum", {"items": [1, 2, 3]})
        self.assertEqual(self.queue.status(task_id).status, "pending")

        status = self._wait(task_id)
        self.assertEqual(status.status, "finished")
        self.assertEqual(status.progress, 1.0)
        self.assertEqual(status.detail["result"]["total"], 6)

    def test_unregistered_task_fails(self):
        self.queue.start_consumers()
        task_id = self.queue.enqueue("no_such", {})
        status = self._wait(task_id)
        self.assertEqual(status.status, "failed")
        self.assertIn("未注册", status.detail["error"])

    def _wait(self, task_id, timeout=15.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            status = self.queue.status(task_id)
            if status and status.status in ("finished", "failed"):
                return status
            time.sleep(0.2)
        self.fail("任务超时未完成")


if __name__ == "__main__":
    unittest.main()