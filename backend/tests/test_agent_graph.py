"""Agent LangGraph 引擎单测：工具循环（非流式/流式）+ 断点续跑。"""

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from agent import ToolLoop
from agent.checkpoint import CheckpointStore
from agent.context import SystemContext
from agent.state import budget_ok
from core.models import ChatResponse, ChatStreamEvent
from infra.adapters.storage import SqliteRepo
from modules.tools import ToolService

PROMPTS = Path(__file__).resolve().parent.parent / "template" / "prompts"

# 一轮工具调用（set_goal，无外部依赖） → 一轮最终答案
_TOOL_CALL = {
    "id": "call_1",
    "name": "set_goal",
    "arguments": '{"goal": "Briefing"}',
}
_SCRIPT = [
    ("", [_TOOL_CALL], "tool_calls"),
    ("最终答案", [], "stop"),
]


class FakeChat:
    """脚本化对话模型：按轮次返回 (content, tool_calls, finish_reason)。"""

    def __init__(self, script):
        self._script = list(script)
        self.round = 0

    def _next(self):
        item = self._script[min(self.round, len(self._script) - 1)]
        self.round += 1
        return item

    def chat(self, messages, **kwargs):
        content, tool_calls, reason = self._next()
        return ChatResponse(content=content, tool_calls=tool_calls, finish_reason=reason)

    def chat_stream(self, messages, **kwargs):
        content, tool_calls, reason = self._next()
        if content:
            yield ChatStreamEvent(type="content", text=content)
        if tool_calls:
            yield ChatStreamEvent(type="tool_calls", calls=tool_calls)
        yield ChatStreamEvent(type="finish", reason=reason)


class FakeDataStore:
    def __init__(self):
        self.turns = []

    def insert_session_turn(self, session_id, messages):
        self.turns.append(list(messages))

    def get_session_history(self, session_id):
        return []


def _cfg(max_iter=5):
    return SimpleNamespace(
        agent_max_tool_iter=max_iter,
        agent_max_output_tokens=2048,
        context_window_tokens=200000,
        llm_model="fake-model",
        llm_reasoning_effort=None,
        storage_data_dir="",
    )


def _loop(script, max_iter=5, data_store=None, checkpoint_store=None):
    return ToolLoop(
        FakeChat(script),
        _cfg(max_iter),
        data_store=data_store,
        vector_store=None,
        system_context=SystemContext(str(PROMPTS)),
        checkpoint_store=checkpoint_store,
    )


class AgentGraphTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # 运行时工具只从数据库加载：用内存库种子 + load_defs 填充全局注册表
        from agent.tools import registry as _reg

        svc = ToolService(SqliteRepo("sqlite:///:memory:"))
        svc.seed_builtins()
        _reg.load_defs(svc.runtime_defs())

    def test_nonstream_tool_loop_returns_final_answer(self):
        ds = FakeDataStore()
        loop = _loop(_SCRIPT, data_store=ds)
        ans = loop.generate_answer("你好", session_id="s1", partition="u")
        self.assertEqual(ans, "最终答案")
        self.assertTrue(ds.turns, "回合应被持久化")
        # 工具结果也应在历史里（set_goal 的返回）
        joined = "".join(str(m.get("content", "")) for turn in ds.turns for m in turn)
        self.assertIn("Briefing", joined)

    def test_stream_emits_tool_and_final_events(self):
        events = []
        loop = _loop(_SCRIPT)
        gen = loop.generate_answer("你好", stream=True, session_id="s2", emit_event=events.append)
        for _ in gen:
            pass

        statuses = [e.get("status") for e in events if e.get("type") == "status"]
        self.assertIn("thinking", statuses)
        self.assertIn("calling_tool", statuses)
        self.assertIn("tool_result", statuses)
        self.assertIn("finished", statuses)
        self.assertTrue(
            any(e.get("type") == "token" and "最终答案" in e.get("text", "") for e in events)
        )

    def test_checkpoint_resume(self):
        tmp = tempfile.mkdtemp()
        try:
            url = "sqlite:///" + os.path.join(tmp, "cp.db")
            store = CheckpointStore(SqliteRepo(url))
            ds = FakeDataStore()
            # max_iter=1：工具轮后即达限 → 保留快照
            loop = _loop(_SCRIPT, max_iter=1, data_store=ds, checkpoint_store=store)

            ans = loop.generate_answer("你好", session_id="s3")
            self.assertIn("上限", ans)
            self.assertIsNotNone(store.load("s3"), "达限应保留检查点")

            resumed = loop.resume_from_checkpoint("s3", extra_iterations=2)
            self.assertEqual(resumed, "最终答案")
            self.assertIsNone(store.load("s3"), "完成后应清除检查点")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_resume_without_checkpoint_returns_none(self):
        tmp = tempfile.mkdtemp()
        try:
            store = CheckpointStore(SqliteRepo("sqlite:///" + os.path.join(tmp, "cp.db")))
            loop = _loop(_SCRIPT, checkpoint_store=store)
            self.assertIsNone(loop.resume_from_checkpoint("nope"))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_running_compression_frees_budget(self):
        # 超 token 预算：运行中压缩旧工具结果后达标，避免提前熔断
        loop = _loop(_SCRIPT, max_iter=5)
        long = "a" * 4000  # 约 1000 token/条
        state = {
            "messages": [
                {"role": "tool", "tool_call_id": str(i), "content": long}
                for i in range(6)
            ],
            "iteration": 1,
            "max_iterations": 5,
            "context_window_tokens": 5000,
        }
        self.assertFalse(budget_ok(state))
        self.assertTrue(loop._try_compress_context(state))
        self.assertTrue(budget_ok(state))

    def test_running_compression_skipped_at_iter_limit(self):
        # 迭代达限时压缩无效，直接返回 False 交给上层熔断
        loop = _loop(_SCRIPT, max_iter=1)
        state = {
            "messages": [{"role": "tool", "tool_call_id": "1", "content": "a" * 1000}],
            "iteration": 1,
            "max_iterations": 1,
            "context_window_tokens": 10,
        }
        self.assertFalse(loop._try_compress_context(state))

    def test_temperature_from_config(self):
        # 配置缺失 → 回退 0.3
        self.assertEqual(_loop(_SCRIPT)._temperature, 0.3)
        # 显式配置生效
        loop = ToolLoop(
            FakeChat(_SCRIPT),
            SimpleNamespace(**{**_cfg().__dict__, "llm_temperature": 0.9}),
            data_store=None, vector_store=None,
            system_context=SystemContext(str(PROMPTS)),
        )
        self.assertEqual(loop._temperature, 0.9)
        # 非法值 → 回退 0.3
        loop_bad = ToolLoop(
            FakeChat(_SCRIPT),
            SimpleNamespace(**{**_cfg().__dict__, "llm_temperature": ""}),
            data_store=None, vector_store=None,
            system_context=SystemContext(str(PROMPTS)),
        )
        self.assertEqual(loop_bad._temperature, 0.3)


if __name__ == "__main__":
    unittest.main()
