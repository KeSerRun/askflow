"""QueryService 会话级并发防护单测（同一会话同一时刻只允许一个生成）。"""

import asyncio
import unittest

from core.app_errors import Conflict
from modules.query import QueryService


class _FakeRunner:
    """最小 runner 替身：run_agent 返回答案或事件生成器。"""

    def run_agent(self, session_id, question, partition=None, style=None, workflow=None, stream=False):
        if stream:
            def gen():
                yield {"type": "token", "text": "hi"}
            return gen()
        return "answer"

    def resume_agent(self, session_id, *, answer=None, extra_iterations=0, stream=False):
        if stream:
            def gen():
                yield {"type": "token", "text": "resumed"}
            return gen()
        return "resumed"

    def cancel_generation(self, session_id):
        self.cancelled = session_id


class _FakeRunnerNoCheckpoint:
    """无检查点：resume_agent(stream=True) 返回 None。"""

    def resume_agent(self, session_id, *, answer=None, extra_iterations=0, stream=False):
        return None

    def cancel_generation(self, session_id):
        pass


class QueryServiceGuardTest(unittest.TestCase):
    def setUp(self):
        self.svc = QueryService(_FakeRunner())

    def test_stream_blocks_same_session(self):
        g1 = self.svc.stream(user_id=1, session_id="s1", question="q")
        self.assertTrue(self.svc.is_generating("s1"))
        with self.assertRaises(Conflict):
            self.svc.stream(user_id=1, session_id="s1", question="q")
        list(g1)  # 消费完 → 释放
        self.assertFalse(self.svc.is_generating("s1"))
        # 释放后可以再次触发
        list(self.svc.stream(user_id=1, session_id="s1", question="q"))

    def test_different_sessions_independent(self):
        g1 = self.svc.stream(user_id=1, session_id="s1", question="q")
        g2 = self.svc.stream(user_id=1, session_id="s2", question="q")  # 不冲突
        list(g1)
        list(g2)

    def test_release_on_client_close(self):
        g = self.svc.stream(user_id=1, session_id="s1", question="q")
        self.assertTrue(self.svc.is_generating("s1"))
        g.close()  # 客户端断开 → GeneratorExit → finally 释放
        self.assertFalse(self.svc.is_generating("s1"))

    def test_ask_blocked_while_streaming(self):
        g = self.svc.stream(user_id=1, session_id="s1", question="q")
        with self.assertRaises(Conflict):
            asyncio.run(self.svc.ask(user_id=1, session_id="s1", question="q"))
        list(g)

    def test_ask_returns_answer_and_releases(self):
        self.assertEqual(asyncio.run(self.svc.ask(user_id=1, session_id="s1", question="q")), "answer")
        self.assertFalse(self.svc.is_generating("s1"))

    def test_stream_resume_yields_and_releases(self):
        g = self.svc.stream_resume(session_id="s1", answer="yes")
        self.assertTrue(self.svc.is_generating("s1"))
        events = list(g)  # 流式续跑 → 事件生成器
        self.assertEqual(events, [{"type": "token", "text": "resumed"}])
        self.assertFalse(self.svc.is_generating("s1"))

    def test_stream_resume_without_checkpoint(self):
        svc = QueryService(_FakeRunnerNoCheckpoint())
        events = list(svc.stream_resume(session_id="s1", answer="yes"))
        self.assertEqual(events[0]["text"], "没有可恢复的进行中生成。")
        self.assertFalse(svc.is_generating("s1"))


if __name__ == "__main__":
    unittest.main()
