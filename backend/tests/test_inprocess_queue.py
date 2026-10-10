"""InProcessTaskQueue 单元测试：投递/状态/结果/异常。"""

import unittest

from infra.adapters.queue import InProcessTaskQueue


class InProcessTaskQueueTest(unittest.TestCase):
    def setUp(self):
        self.queue = InProcessTaskQueue(max_workers=4)

    def tearDown(self):
        self.queue.shutdown()

    def test_enqueue_and_finish(self):
        self.queue.register_handler("sum", lambda p: {"total": sum(p["items"])})
        task_id = self.queue.enqueue("sum", {"items": [1, 2, 3]})
        self.assertIsNotNone(self.queue.status(task_id))

        status = self._wait(task_id)
        self.assertEqual(status.status, "finished")
        self.assertEqual(status.progress, 1.0)
        self.assertEqual(status.detail["result"]["total"], 6)

    def test_unregistered_task_fails(self):
        task_id = self.queue.enqueue("no_such_task", {})
        status = self._wait(task_id)
        self.assertEqual(status.status, "failed")
        self.assertIn("未注册", status.detail["error"])

    def test_unknown_status_returns_none(self):
        self.assertIsNone(self.queue.status("not-exist"))

    def _wait(self, task_id, timeout=5.0):
        import time

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            status = self.queue.status(task_id)
            if status and status.status in ("finished", "failed"):
                return status
            time.sleep(0.02)
        self.fail("任务超时未完成")


if __name__ == "__main__":
    unittest.main()