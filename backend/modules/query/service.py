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

import json
import threading
from collections.abc import Iterator

from core.app_errors import Conflict
from core.concurrency import to_thread


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
        """可用工作流列表（由 backend/template/prompts/workflow/ 自动发现）。"""
        return self._runner.tool_loop.system_context.workflow_router.get_workflow_list()

    # ── 问答 ──

    @staticmethod
    def _with_image_refs(question: str, images: list[str] | None) -> str:
        """把附带图片的对象键注入问题文本，引导模型用 search_knowledge_base 图文检索。"""
        refs = [str(i).strip() for i in (images or []) if str(i).strip()]
        if not refs:
            return question
        key_list = json.dumps(refs, ensure_ascii=False)
        return (question.rstrip() + "\n\n"
                f"[用户附带了图片，图片对象键：{key_list}。如需检索与图片相关的内容，请调用 "
                "search_knowledge_base 并在 images 参数传入这些对象键（可同时给 queries 做文本混合检索）。]")

    def upload_query_image(self, *, user_id: int, session_id: str, data: bytes,
                           filename: str = "pasted.png") -> str:
        """把剪贴板/上传的图片存入对象存储，返回对象键（供工具检索）。

        - 正常对话：``sessions/{user_id}/{session_id}/query_img/{uuid}.ext``，删除会话时随目录清理；
        - 空会话（管理端工具测试等，无真实会话）：存 ``tmp_query_img/{user_id}/{uuid}.ext``，
          每次上传前自动清空该用户旧的测试图（只保留最新一张），避免堆积。
        """
        import uuid as _uuid
        from pathlib import Path as _Path

        from infra.util.logger import logger

        if not data:
            raise ValueError("图片为空")
        store = getattr(self._runner, "object_store", None)
        if store is None:
            raise RuntimeError("对象存储不可用")
        ext = _Path(filename or "pasted.png").suffix.lstrip(".").lower() or "png"
        if ext not in ("png", "jpg", "jpeg", "gif", "webp", "bmp"):
            ext = "png"
        sid = str(session_id or "").strip()

        def _clean_prefix(prefix: str) -> None:
            try:
                keys = [k for k in (store.list_keys(prefix) or [])]
            except Exception:  # noqa: BLE001
                logger.debug(f"query_img 清理列举失败: {prefix}")
                return
            if keys:
                try:
                    store.delete_keys(keys)
                except Exception:  # noqa: BLE001
                    logger.debug(f"query_img 清理删除失败: {prefix} {len(keys)} 个")

        if sid:
            folder = f"sessions/{int(user_id)}/{_Path(sid).stem}/query_img"
        else:
            # 管理端测试（无会话）：专用临时目录，先清旧的（保留最新一张）
            folder = f"tmp_query_img/{int(user_id)}"
            _clean_prefix(folder + "/")
            # 清理早期遗留的 default 测试目录
            _clean_prefix(f"sessions/{int(user_id)}/default/")
        key = f"{folder}/{_uuid.uuid4().hex[:12]}.{ext}"
        store.put_bytes(key, data, content_type=f"image/{'jpeg' if ext == 'jpg' else ext}")
        return key

    async def ask(self, *, user_id: int, session_id: str, question: str,
                  style: str | None = None, workflow: str | None = None,
                  images: list[str] | None = None) -> str:
        """非流式问答（同步引擎调用卸载到线程）。

        Raises:
            Conflict: 该会话已有生成在跑。
        """
        self._acquire(session_id)
        try:
            return await to_thread(
                self._runner.run_agent,
                session_id, self._with_image_refs(question, images),
                partition=str(user_id), style=style, workflow=workflow, stream=False,
            )
        finally:
            self._release(session_id)

    async def resume(self, *, session_id: str, answer: str | None = None,
                     extra_iterations: int = 0) -> str:
        """从检查点续跑未完成的生成；``answer`` 为澄清问题的用户回答（注入后继续）。"""
        self._acquire(session_id)
        try:
            result = await to_thread(
                self._runner.resume_agent,
                session_id,
                answer=answer,
                extra_iterations=extra_iterations,
            )
        finally:
            self._release(session_id)
        return result or "没有可恢复的进行中生成。"

    def stream(self, *, user_id: int, session_id: str, question: str,
               style: str | None = None, workflow: str | None = None,
               images: list[str] | None = None) -> Iterator:
        """流式问答（返回引擎事件生成器）。

        同步占位（冲突可在响应开始前返回 409），生成器结束/关闭时自动释放。

        Raises:
            Conflict: 该会话已有生成在跑。
        """
        self._acquire(session_id)
        gen = self._runner.run_agent(
            session_id, self._with_image_refs(question, images),
            partition=str(user_id), style=style, workflow=workflow, stream=True,
        )
        return _GuardedStream(gen, lambda: self._release(session_id))

    def stream_resume(self, *, session_id: str, answer: str | None = None,
                      extra_iterations: int = 0) -> Iterator:
        """流式续跑未完成的生成（澄清后继续 / 断点续跑）。

        与 :meth:`stream` 一致：同步占位（冲突在响应开始前抛），生成器结束/关闭时自动释放。
        """
        self._acquire(session_id)
        gen = self._runner.resume_agent(
            session_id, answer=answer, extra_iterations=extra_iterations, stream=True,
        )
        if gen is None:
            self._release(session_id)
            return iter((
                {"type": "token", "text": "没有可恢复的进行中生成。"},
                {"type": "status", "status": "finished"},
            ))
        return _GuardedStream(gen, lambda: self._release(session_id))

    def cancel(self, session_id: str) -> None:
        """中断指定会话正在进行的生成（随后 _wrap_stream 的 finally 会释放占位）。"""
        self._runner.cancel_generation(session_id)
