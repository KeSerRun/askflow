"""modules.query_service —— 问答用例（封装对 Agent 引擎的调用）。

把原先散在 controller 的编排集中于此：
  - 风格/工作流列表读取
  - 非流式问答（同步引擎调用卸载到线程）
  - 流式问答（返回引擎事件生成器）
  - 中断生成

**会话级状态防护**：同一 ``session_id`` 同一时刻只允许一个生成，避免前端连点
触发多个并发 loop（重复写历史 / 取消信号互相覆盖）。冲突抛 ``Conflict``（HTTP 409）。

依赖组合根注入的 Agent runner（IntegratedSystem）。
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Iterator

from core.errors import Conflict


class _GuardedStream:
    """包装引擎事件生成器：无论耗尽 / 异常 / close / 被回收，都释放会话占位。

    相比 `yield from` 的生成器包装，这里能覆盖"尚未开始迭代就被 close/丢弃"的场景，
    避免会话占位泄漏（否则该会话将永远无法再次触发）。
    """

    def __init__(self, gen: Iterator, release):
        self._gen = gen
        self._release = release
        self._done = False

    def __iter__(self):
        return self

    def __next__(self):
        try:
            return next(self._gen)
        except StopIteration:
            self._finish()
            raise
        except BaseException:
            self._finish()
            raise

    def close(self):
        self._finish()
        closer = getattr(self._gen, "close", None)
        if closer:
            closer()

    def _finish(self):
        if not self._done:
            self._done = True
            self._release()

    def __del__(self):
        self._finish()


class QueryService:
    """问答用例。"""

    def __init__(self, runner: object):
        """初始化。

        Args:
            runner: Agent 引擎（提供 run_agent / cancel_generation 与 system_context）。
        """
        self._runner = runner
        self._lock = threading.Lock()
        self._active: set[str] = set()  # 正在生成的 session_id

    # ── 并发防护 ──

    def _acquire(self, session_id: str) -> None:
        """占位该会话；已在生成中则抛 409。"""
        with self._lock:
            if session_id in self._active:
                raise Conflict("该会话正在生成回答，请等待完成或先中断")
            self._active.add(session_id)

    def _release(self, session_id: str) -> None:
        with self._lock:
            self._active.discard(session_id)

    def is_generating(self, session_id: str) -> bool:
        """该会话当前是否在生成中。"""
        with self._lock:
            return session_id in self._active

    # ── 元信息 ──

    def styles(self) -> list:
        """可用回答风格列表（default 置顶）。"""
        styles = self._runner.tool_loop.system_context.style_router.list_skills()
        styles.sort(key=lambda s: (s["value"] != "default", s["label"]))
        return styles

    def workflows(self) -> list:
        """可用工作流列表。"""
        return self._runner.tool_loop.system_context.workflow_router.get_workflow_list()

    # ── 问答 ──

    async def ask(self, *, username: str, session_id: str, question: str,
                  style: str | None = None, workflow: str | None = None) -> str:
        """非流式问答（同步引擎调用卸载到线程）。

        Raises:
            Conflict: 该会话已有生成在跑。
        """
        self._acquire(session_id)
        try:
            return await asyncio.to_thread(
                self._runner.run_agent,
                session_id, question,
                partition=username, style=style, workflow=workflow, stream=False,
            )
        finally:
            self._release(session_id)

    async def resume(self, *, session_id: str, extra_iterations: int = 0) -> str:
        """从检查点续跑未完成的生成（无检查点返回提示文案）。

        Raises:
            Conflict: 该会话已有生成在跑。
        """
        self._acquire(session_id)
        try:
            result = await asyncio.to_thread(
                self._runner.resume_agent,
                session_id,
                extra_iterations=extra_iterations,
            )
        finally:
            self._release(session_id)
        return result or "没有可恢复的进行中生成。"

    def stream(self, *, username: str, session_id: str, question: str,
               style: str | None = None, workflow: str | None = None) -> Iterator:
        """流式问答（返回引擎事件生成器）。

        同步占位（冲突可在响应开始前返回 409），生成器结束/关闭时自动释放。

        Raises:
            Conflict: 该会话已有生成在跑。
        """
        self._acquire(session_id)
        gen = self._runner.run_agent(
            session_id, question,
            partition=username, style=style, workflow=workflow, stream=True,
        )
        return _GuardedStream(gen, lambda: self._release(session_id))

    def cancel(self, session_id: str) -> None:
        """中断指定会话正在进行的生成（随后 _wrap_stream 的 finally 会释放占位）。"""
        self._runner.cancel_generation(session_id)
