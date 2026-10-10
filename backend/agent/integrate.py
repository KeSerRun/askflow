"""IntegratedSystem: 集成数据存储 + RAG 问答能力，对外提供统一的问答和 CLI 接口。

包括：会话历史管理、风格切换检测、流式/非流式问答、CLI 命令分发。
"""

import os
import threading

from config.app_config import AppConfig  # noqa: F401  # 便于按名引用
from config.paths import _project_root as _BACKEND_ROOT
from infra.logger import logger

from .checkpoint import CheckpointStore
from .context import SystemContext
from .governor import compress_history, truncate_history
from .loop import ToolLoop

# ── 集成系统 ──


class IntegratedSystem:
    """集成数据存储 + RAG 问答能力，对外提供统一问答和 CLI 入口。"""

    def __init__(self, container):
        """初始化集成系统。

        组件全部取自传入的组合根容器（ports 体系）；SystemContext 按 prompts 目录构建。

        Args:
            container: 组合根容器（必填，由 app 入口 / compositor 提供）。
        """
        cfg = container.config

        self.data_store = container.history_service
        self.chat_client = container.chat_model
        self.embed_client = container.embedder
        self.vector_store = container.vector_store

        self.system_context = SystemContext(os.path.join(_BACKEND_ROOT, "prompts"))

        # 断点续跑：配置开启且有通用仓储时启用
        self.checkpoint_store = None
        if getattr(cfg, "agent_checkpoint_enabled", False):
            repo = getattr(container, "repo", None)
            if repo is not None:
                self.checkpoint_store = CheckpointStore(repo)
                logger.info("检查点已启用（agent_checkpoint_enabled=true）")

        self.tool_loop = ToolLoop(
            chat_client=self.chat_client,
            data_store=self.data_store,
            vector_store=self.vector_store,
            system_context=self.system_context,
            cfg=cfg,
            checkpoint_store=self.checkpoint_store,
        )

        self.session_last_style: dict[str, str] = {}
        self._cancel_events: dict[str, threading.Event] = {}


    def cancel_generation(self, session_id: str) -> None:
        """中断指定会话的正在进行的生成。

        Args:
            session_id: 要中断的会话 ID。
        """
        event = self._cancel_events.get(session_id)
        if event:
            event.set()
            logger.info(f"已发送中断信号: session={session_id}")

    def resume_agent(
        self,
        session_id: str,
        *,
        extra_iterations: int = 0,
        stream: bool = False,
    ):
        """从最近检查点续跑未完成的生成（无检查点返回 None）。

        中断 / 崩溃 / 达限后会保留图快照；调用本方法可从断点继续，
        ``extra_iterations`` 可在续跑时追加迭代预算。

        Args:
            session_id: 会话 ID。
            extra_iterations: 续跑时额外追加的迭代次数（默认 0）。
            stream: 是否流式续跑（默认 False）。

        Returns:
            非流式返回答案字符串；流式返回事件生成器；无检查点返回 None。
        """
        if self.checkpoint_store is None:
            return None
        return self.tool_loop.resume_from_checkpoint(
            session_id, extra_iterations=extra_iterations, stream=stream,
        )


    # ── 会话历史管理 ──

    def get_history(self, session_id):
        """读取会话历史并展开为 LLM 输入格式。

        超过上下文预算时自动压缩工具结果或截断历史（由 governor 模块处理）。

        Args:
            session_id: 会话 ID。

        Returns:
            LLM 输入格式的消息列表。
        """
        raw = self.data_store.get_session_history(session_id) or []

        if not raw:
            return []
        messages = []

        for h in raw:
            self._append_history_item(messages, h)


        # ── 上下文预算检查：超限时压缩历史中的工具结果 ──
        _cfg = getattr(self.tool_loop, "cfg", None)
        budget = int(_cfg.context_window_chars * _cfg.context_input_ratio)
        total = sum(len(str(m.get("content", "") or "")) for m in messages)
        if total > budget and len(raw) > 2:
            # 因为只压缩工具结果，所以需要压缩比 0.5 倍
            compress_history(self.data_store, session_id, raw,
                             compression_ratio=min(_cfg.context_compression_ratio * 0.5, 1.0), archive=True)
            messages.clear()
            raw = self.data_store.get_session_history(session_id) or []
            for h in raw:
                self._append_history_item(messages, h)

        # ── 第二关：压缩后仍超预算 → 截断历史 ──
        total = sum(len(str(m.get("content", "") or "")) for m in messages)
        if total > budget and len(raw) > 2:
            # 这里保留压缩比，确保达标
            target = int(budget * _cfg.context_compression_ratio)
            truncate_history(self.data_store, session_id, raw,
                             target, archive=False)
            messages.clear()
            raw = self.data_store.get_session_history(session_id) or []
            for h in raw:
                self._append_history_item(messages, h)

        logger.debug(f"get_history: raw={len(raw)} 条, 总字符 ~{sum(len(str(m.get('content', '') or '')) for m in messages)}, "
                     f"返回 {len(messages)} 条消息")

        return messages


    # ── 历史辅助方法 ──

    @staticmethod
    def _append_history_item(messages: list, h: dict) -> None:
        """将一条 history 条目追加到 messages。

        Args:
            messages: 目标消息列表（会就地修改）。
            h: history 条目字典，支持 'turn'、'event' 和 'qa' 三种类型。
        """
        if h.get('type') == 'turn':
            turn_msgs = h.get('messages', [])
            for m in turn_msgs:
                messages.append(m)
        elif h.get('type') == 'event':
            tag = IntegratedSystem._event_to_tag(
                h.get('event_type', ''), h.get('files', [])
            )
            if tag:
                messages.append({'role': 'user', 'content': tag})
        else:
            messages.append({'role': 'user', 'content': h.get('user', '')})
            messages.append({'role': 'assistant', 'content': h.get('assistant', '')})

    @staticmethod
    def _event_to_tag(event_type: str, files: list) -> str:
        """将事件转换为 <operation：...> 文本，供 LLM 感知用户最近操作。

        Args:
            event_type: 事件类型（如 'delete_all'、'upload'、'delete'、'style_change'）。
            files: 事件涉及的文件列表。

        Returns:
            格式化的操作描述字符串，无匹配时返回空字符串。
        """
        if event_type == 'delete_all':
            return "<operation：clear all uploaded files>"
        if not files:
            return ""
        head = files[:3]
        suffix = "等" if len(files) > 3 else ""
        if event_type == 'upload':
            return f"<operation：upload files: {', '.join(head)}{suffix}>"
        if event_type == 'delete':
            return f"<operation：delete files: {', '.join(head)}{suffix}>"
        if event_type == 'style_change':
            new_style = files[0] if files else 'default'
            return f"<operation：switch answer style to {new_style}>"
        return ""

    def _check_style_change(self, session_id: str, style: str | None) -> None:
        """检测 style 切换，记录事件到历史。

        Args:
            session_id: 会话 ID。
            style: 新的回答风格名称。
        """
        prev = self.session_last_style.get(session_id)
        if prev is not None and prev != style:
            self.data_store.insert_session_event(session_id, 'style_change', [str(style or 'default')])
            logger.info(f"style 切换: {prev} → {style or 'default'}")
        self.session_last_style[session_id] = style or 'default'


    # ── 问答入口 ──

    def run_agent(self, session_id, question, partition: str = None, style: str | None = None, stream=False, workflow: str | None = None):
        """处理用户查询，返回答案（非流式）或事件生成器（流式）。

        调用方（API）已持有会话锁。

        Args:
            session_id: 会话 ID。
            question: 用户问题。
            partition: 知识库分区（用户名）。
            style: 回答风格。
            stream: 是否流式。
            workflow: 工作流名称（None 为自动识别）。

        Returns:
            非流式模式返回答案字符串；流式模式返回事件生成器。
        """
        if stream:
            return self._run_agent_stream(session_id, question, partition, style, workflow=workflow)

        self._check_style_change(session_id, style)
        history = self.get_history(session_id)

        try:
            answer = self.tool_loop.generate_answer(
                question,
                stream=False,
                history=history,
                partition=partition,
                session_id=session_id,
                style=style,
                workflow=workflow,
            )
            logger.debug(f"回答成功 len={len(answer)}")
        except Exception as e:
            logger.error(f"回答失败: {e}")
            answer = f"抱歉，处理请求时发生了错误: {e}"
            self.data_store.insert_session_history(session_id, question, answer)
            return answer

        return answer


    def _run_agent_stream(self, session_id, question, partition=None, style=None, workflow=None):
        """流式版本的 run_agent，使用线程安全队列传递事件。

        Args:
            session_id: 会话 ID。
            question: 用户问题。
            partition: 知识库分区（用户名）。
            style: 回答风格。
            workflow: 工作流名称。

        Yields:
            事件字典，与 _run_tool_loop_stream 的 yield 格式相同：
            - {"type": "token", "text": "..."}
            - {"type": "status", "status": "..."}
            - {"type": "reasoning", "text": "..."}
        """
        self._check_style_change(session_id, style)
        logger.debug(f"会话 session={session_id}")

        cancel_event = threading.Event()
        self._cancel_events[session_id] = cancel_event

        def is_cancelled():
            return cancel_event.is_set()


        import queue as _queue
        session_queue = _queue.Queue()
        _DONE = object()

        def _worker():
            try:
                gen = self.tool_loop.generate_answer(
                    query=question,
                    stream=True,
                    history=self.get_history(session_id),
                    partition=partition,
                    session_id=session_id,
                    style=style,
                    workflow=workflow,
                    cancel_check=is_cancelled,
                    emit_event=session_queue.put,
                )
                for _ in gen:
                    pass
            except Exception as e:
                logger.error(f"生成回答异常: {e}")
                session_queue.put({"type": "status", "status": "error", "error": str(e)})
            finally:
                session_queue.put(_DONE)

        t = threading.Thread(target=_worker, daemon=True)
        t.start()

        ans = []
        try:
            while True:
                try:
                    ev = session_queue.get(timeout=1)
                except _queue.Empty:
                    if is_cancelled():
                        yield {"type": "status", "status": "cancelled"}
                        logger.info(f"生成被中断: session={session_id}")
                        return
                    if not t.is_alive():
                        logger.warning(f"工作线程已退出，session={session_id}")
                        break
                    continue
                if ev is _DONE:
                    break
                if is_cancelled():
                    yield {"type": "status", "status": "cancelled"}
                    logger.info(f"生成被中断: session={session_id}")
                    return
                if ev.get("type") == "token":
                    ans.append(ev.get("text", ""))
                yield ev
        finally:
            self._cancel_events.pop(session_id, None)
            t.join(timeout=2)

        answer = ''.join(ans)
        logger.debug(f"回答成功 len={len(answer)}")

