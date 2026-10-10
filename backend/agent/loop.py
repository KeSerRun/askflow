"""RAG agent: LangGraph 状态机驱动的 tool-calling 循环。

图结构（替代手写 while 循环）：

    START → agent ──(tools)──▶ tools ──▶ agent
              │                    ▲
              ├──(retry)──▶ retry ─┘
              └──(finish)──────────▶ END

- ``agent`` 节点：调 LLM（内存放 reasoning/token 流，或一次取回），产 assistant 消息与工具请求；
- ``route`` 条件边：有工具 → tools；需要重试 → retry；否则 finish；
- ``tools`` 节点：并发执行工具（沿用原分批逻辑）、写 calling_tool/tool_result 事件、澄清检查、回合持久化；
- ``retry`` 节点：空回答 / 截断续写时补一条 user 提示再回 agent。

事件协议（对前端不变）：token / reasoning / status(thinking|calling_tool|tool_result|retrying|finished)。

取消/事件注入走 ``config["configurable"]``，**不进入图状态**（保证状态可 JSON 序列化 + checkpoint）。
"""

from __future__ import annotations

from collections.abc import Callable

from langchain_core.runnables.config import RunnableConfig
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph

from core.models import ChatResponse, ChatStreamEvent
from infra.logger import log_llm_input, logger

from .checkpoint import CheckpointStore
from .context import SystemContext
from .state import (
    GraphState,
    assistant_message,
    budget_ok,
    last_assistant_content,
    tool_result_message,
)
from .tools import registry
from .tools._infra_handlers import _get_goal_line
from .tools.registry import ToolContext

# ── 工具调用展示解析（前端 status 事件） ──


def _parse_tool_display(tc: dict) -> dict:
    """从工具调用参数提取前端展示信息。"""
    import json as _json

    info = {"tool": tc["name"]}
    try:
        args = _json.loads(tc.get("arguments") or "{}")
        if "queries" in args:
            info["query"] = args["queries"]
        elif "query" in args:
            info["query"] = [args["query"]]
        if "filename" in args:
            info["filename"] = args["filename"]
    except Exception:
        pass
    return info


# ── 工具循环 ──


class ToolLoop:
    """RAG 系统核心：LangGraph 编排 LLM 自主决策检索、拆解查询、生成答案。"""

    def __init__(
        self,
        chat_client: object,
        cfg: object,
        data_store: object = None,
        vector_store: object = None,
        system_context: SystemContext = None,
        checkpoint_store: CheckpointStore | None = None,
    ):
        """初始化 ToolLoop。

        Args:
            chat_client: 对话模型适配器（.chat / .chat_stream，返回 ChatResponse / ChatStreamEvent）。
            cfg: 配置对象（agent_max_tool_iter / context_window_chars 等）。
            data_store: 历史数据存储（回合持久化）。
            vector_store: 向量库实例。
            system_context: 系统上下文（身份/风格/工作流）。
            checkpoint_store: 断点快照存储（None 则不启用 checkpoint/续跑）。
        """
        self.cfg = cfg
        self.chat_client = chat_client
        self.data_store = data_store
        self.vector_store = vector_store
        self.system_context = system_context
        self.chat_model = getattr(cfg, "llm_model", None)
        self.checkpoint_store = checkpoint_store
        self.graph = self._build_graph()

    # ── 图构建 ──

    def _build_graph(self):
        g = StateGraph(GraphState)
        g.add_node("agent", self._agent_node)
        g.add_node("tools", self._tools_node)
        g.add_node("retry", self._retry_node)
        g.add_edge(START, "agent")
        g.add_conditional_edges(
            "agent",
            lambda s: s.get("next_action", "finish"),
            {"tools": "tools", "retry": "retry", "finish": END},
        )
        g.add_edge("tools", "agent")
        g.add_edge("retry", "agent")
        return g.compile()

    # ── 系统消息 / 工具上下文 ──

    @property
    def _max_output_tokens(self) -> int:
        """输出上限：优先 max_output_tokens，回退 agent_max_output_chars。"""
        return getattr(
            self.cfg, "max_output_tokens",
            getattr(self.cfg, "agent_max_output_chars", 8192),
        )

    def _build_system_message(self, style=None, workflow=None) -> str:
        """构造 system message：identity + 日期 + 风格 + 工作流。"""
        parts = [self.system_context.identity or ""]

        import time as _time
        from datetime import datetime as _dt

        _tz = _time.tzname
        parts.append(
            f"\n当前日期: {_dt.now().strftime('%Y年%m月%d日 %A %H:%M')} "
            f"(时区: {_tz[0] if _tz else 'UTC'})"
        )

        if style and style != "style-default":
            skill = self.system_context.style_router.get_skill(style)
            if skill and skill.template:
                parts.append(f"\n\n{skill.template}")

        wf_name = workflow if workflow and workflow != "__auto__" else None
        if wf_name:
            wf_content = self.system_context.workflow_router.get_workflow_content(wf_name)
            if wf_content:
                parts.append(f"\n\n---\n# 工作流: {wf_name}\n{wf_content}")
                logger.debug(f"工作流已加载: {wf_name}")
            else:
                logger.warning(f"工作流 '{wf_name}' 未找到")
        else:
            wf_summaries = self.system_context.workflow_router.get_workflow_summaries()
            if wf_summaries:
                parts.append(
                    f"\n\n---\n# 工作流\n{wf_summaries}\n"
                    f"如需加载完整工作流指令，请调用 read_workflow 工具。"
                )
        return "".join(parts)

    def _build_tool_context(self, state: dict, extra: dict | None = None) -> ToolContext:
        """从图状态构建工具运行时上下文。"""
        return ToolContext(
            vector_store=self.vector_store,
            partition=state.get("partition"),
            data_store=self.data_store,
            session_id=state.get("session_id") or "",
            workflow_router=(
                getattr(self.system_context, "workflow_router", None)
                if self.system_context else None
            ),
            config=self.cfg,
            data_dir=getattr(self.cfg, "storage_data_dir", "") or "",
        )

    # ── LLM 调用归一化 ──

    def _common_chat_kwargs(self, tools, tool_choice) -> dict:
        return dict(
            tools=tools,
            tool_choice=tool_choice,
            temperature=0.7,
            max_tokens=self._max_output_tokens,
            reasoning_effort=getattr(self.cfg, "llm_reasoning_effort", None),
        )

    def _chat_response(self, state: dict, tools, tool_choice) -> ChatResponse:
        """非流式 LLM 调用，返回统一 ChatResponse。"""
        common = self._common_chat_kwargs(tools, tool_choice)
        chat = self.chat_client
        if hasattr(chat, "chat_stream"):
            return chat.chat(messages=state.get("messages"), **common)
        raw = chat.chat_with_tools(
            messages=state.get("messages"), model=self.chat_model,
            stream=False, **common,
        )
        return ChatResponse(
            content=raw.get("content") or "",
            tool_calls=raw.get("tool_calls") or [],
            finish_reason=raw.get("finish_reason"),
        )

    def _chat_events(self, state: dict, tools, tool_choice):
        """流式 LLM 调用，返回 Iterator[ChatStreamEvent]。"""
        common = self._common_chat_kwargs(tools, tool_choice)
        chat = self.chat_client
        if hasattr(chat, "chat_stream"):
            return chat.chat_stream(messages=state.get("messages"), **common)

        def _wrap():
            for ev in chat.chat_with_tools(
                messages=state.get("messages"), model=self.chat_model,
                stream=True, **common,
            ):
                yield ChatStreamEvent(
                    type=ev.get("type", "content"),
                    text=ev.get("text", ""),
                    calls=ev.get("calls", []),
                    reason=ev.get("reason"),
                )
        return _wrap()

    # ── 工具执行 ──

    @staticmethod
    def _execute_single_tool(tc: dict, ctx: ToolContext) -> tuple:
        """执行单个工具调用，带错误兜底。"""
        try:
            res = registry.dispatch(tc["name"], tc["arguments"], ctx=ctx)
            logger.debug(f"工具 {tc['name']} 完成: result_len={len(res)} chars")
            return tc["id"], res
        except Exception as e:
            logger.error(f"工具 {tc['name']} 执行发生严重异常: {e}", exc_info=True)
            return tc["id"], (
                f"(系统提示: 执行工具 {tc['name']} 时发生了严重错误: {e}，"
                f"请尝试使用其他工具或根据现有信息回答)"
            )

    @staticmethod
    def _execute_tool_batch(tool_calls: list, ctx: ToolContext) -> dict:
        """并发执行一批工具调用（按并发安全性分批）。"""
        import concurrent.futures

        from .tools.registry import ToolRegistry

        results: dict = {}
        batches = ToolRegistry.partition_tool_batches(tool_calls)
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(tool_calls)) as executor:
            for batch in batches:
                futures = [
                    executor.submit(ToolLoop._execute_single_tool, tc, ctx)
                    for tc in batch
                ]
                for future in concurrent.futures.as_completed(futures):
                    tc_id, result = future.result()
                    results[tc_id] = result
        return results

    @staticmethod
    def _check_clarification(tool_calls: list) -> str | None:
        """检查工具调用中是否含 ask_user_for_clarification。"""
        import json as _json

        for tc in tool_calls:
            if tc["name"] == "ask_user_for_clarification":
                try:
                    return _json.loads(tc.get("arguments", "{}")).get(
                        "question", "我需要更多信息。"
                    )
                except Exception:
                    return "我需要您提供更多背景信息。"
        return None

    # ── 状态辅助 ──

    def _finish(self, state: dict, message: str) -> dict:
        """构造 end 节点返回（带 finished 事件）。"""
        updates = dict(state)
        updates["final_answer"] = message
        updates["finished"] = True
        updates["next_action"] = "finish"
        return updates

    def _persist_turn(self, state: dict) -> None:
        """把本轮新增消息增量存入历史（与旧 _save_turn_messages 等价）。"""
        ds = self.data_store
        if ds is None:
            return
        try:
            saved_from = max(state.get("saved_idx") or 0, state.get("saved_from") or 0)
            turn_msgs = [
                m for m in state.get("messages", [])[saved_from:]
                if m.get("role") != "system"
            ]
            if not turn_msgs:
                return
            ds.insert_session_turn(state.get("session_id") or "default", turn_msgs)
            state["saved_idx"] = len(state.get("messages", []))
        except Exception as e:
            logger.warning(f"保存完整对话回合失败: {e}")

    def _checkpoint(self, state: dict) -> None:
        """保存该线程的图快照（供断点续跑）。"""
        store = self.checkpoint_store
        if store is None:
            return
        try:
            store.save(state.get("session_id") or "default", dict(state))
        except Exception as e:
            logger.warning(f"checkpoint 保存失败: {e}")

    def _clear_checkpoint(self, state: dict) -> None:
        store = self.checkpoint_store
        if store is None:
            return
        try:
            store.clear(state.get("session_id") or "default")
        except Exception:
            pass

    # ── 图节点：agent ──

    def _agent_node(self, state: dict, config: RunnableConfig) -> dict:
        """LLM 节点：取响应 / 流式 token → 路由。"""
        extra = config.get("configurable") or {}
        emit = extra.get("emit_event")
        cancel = extra.get("cancel_check")
        writer = get_stream_writer()

        if cancel and cancel():
            logger.info("工具循环被中断")
            return {"next_action": "finish"}

        if not budget_ok(state):
            logger.warning(f"tool-loop 达到上限/预算 (iter={state.get('iteration')})")
            # 达限不清 checkpoint：保留快照，允许后续“继续/续跑”
            updates = dict(state)
            updates["final_answer"] = "已达单次工具调用上限，如已有足够信息可直接给出最终答案。"
            updates["next_action"] = "finish"
            return updates

        log_llm_input(state.get("messages", []), round=state.get("iteration", 0), suffix="_sent")

        if emit:
            writer({"type": "status", "status": "thinking"})
            emit({"type": "status", "status": "thinking"})

        if emit:  # 流式：逐 token 产出并累加
            content, tool_calls, reason = self._stream_llm(state, config)
        else:
            try:
                resp = self._chat_response(state, registry.schemas, "auto")
            except Exception as e:
                logger.error(f"LLM tool 调用失败 (round {state.get('iteration')}): {e}")
                return self._finish(state, "抱歉，模型处理请求时发生了错误。")
            content, tool_calls, reason = resp.content or "", resp.tool_calls or [], resp.finish_reason

        if reason == "cancelled":
            return {"next_action": "finish"}
        if reason == "error":
            return self._finish(state, content or "抱歉，模型处理请求时发生了错误。")

        updates = dict(state)
        if tool_calls:
            updates["messages"] = state.get("messages", []) + [assistant_message(content, tool_calls)]
            updates["iteration"] = (state.get("iteration") or 0) + 1
            updates["tool_calls"] = tool_calls
            updates["next_action"] = "tools"
            self._checkpoint(updates)
            return updates

        # 无工具调用 → 空回答重试 / 截断续写重试 / 最终答案
        if not content or not content.strip():
            er = state.get("empty_retries", 0)
            if er < 2:
                updates["next_action"] = "retry"
                updates["retry_op"] = "empty"
                updates["empty_retries"] = er + 1
                if emit:
                    writer({"type": "status", "status": "retrying"})
                    emit({"type": "status", "status": "retrying"})
                return updates
            updates["messages"] = state.get("messages", []) + [assistant_message("")]
            updates["iteration"] = (state.get("iteration") or 0) + 1
        elif reason == "length":
            lr = state.get("length_retries", 0)
            if lr < 3:
                updates["messages"] = state.get("messages", []) + [assistant_message(content)]
                updates["iteration"] = (state.get("iteration") or 0) + 1
                updates["next_action"] = "retry"
                updates["retry_op"] = "continue"
                updates["length_retries"] = lr + 1
                self._checkpoint(updates)
                return updates
            updates["messages"] = state.get("messages", []) + [assistant_message(content)]
            updates["iteration"] = (state.get("iteration") or 0) + 1
        else:
            updates["messages"] = state.get("messages", []) + [assistant_message(content)]
            updates["iteration"] = (state.get("iteration") or 0) + 1

        updates["final_answer"] = content or ""
        updates["finished"] = True
        updates["next_action"] = "finish"
        self._persist_turn(updates)
        self._checkpoint(updates)
        if emit:
            writer({"type": "status", "status": "finished"})
            emit({"type": "status", "status": "finished"})
        return updates

    def _stream_llm(self, state: dict, config: dict):
        """流式 LLM：写 token/reasoning 事件，返回 (累计文本, tool_calls, reason)。"""
        extra = config.get("configurable") or {}
        emit = extra.get("emit_event")
        cancel = extra.get("cancel_check")
        writer = get_stream_writer()

        accumulated = ""
        tool_calls: list[dict] = []
        reason = None
        try:
            for ev in self._chat_events(state, registry.schemas, "auto"):
                if cancel and cancel():
                    return accumulated, [], "cancelled"
                if ev.type == "content":
                    accumulated += ev.text
                    writer({"type": "token", "text": ev.text})
                    if emit:
                        emit({"type": "token", "text": ev.text})
                elif ev.type == "reasoning":
                    writer({"type": "reasoning", "text": ev.text})
                    if emit:
                        emit({"type": "reasoning", "text": ev.text})
                elif ev.type == "tool_calls":
                    tool_calls = ev.calls or []
                elif ev.type == "finish":
                    reason = ev.reason
        except Exception as e:
            logger.error(f"LLM tool 流式调用失败 (round {state.get('iteration')}): {e}", exc_info=True)
            msg = "\n\n抱歉，模型处理请求时发生了错误。"
            writer({"type": "token", "text": msg})
            if emit:
                emit({"type": "token", "text": msg})
            return msg, [], "error"
        return accumulated, tool_calls, reason

    # ── 图节点：tools ──

    def _tools_node(self, state: dict, config: RunnableConfig) -> dict:
        """工具节点：并发执行 + 事件 + 澄清检查 + 回合持久化 + checkpoint。"""
        import re as _re

        extra = config.get("configurable") or {}
        emit = extra.get("emit_event")
        writer = get_stream_writer()

        tool_calls = state.get("tool_calls") or []
        total = len(tool_calls)
        for tc in tool_calls:
            display = _parse_tool_display(tc)
            display["total"] = total
            writer({"type": "status", "status": "calling_tool", **display})
            if emit:
                emit({"type": "status", "status": "calling_tool", **display})

        ctx = self._build_tool_context(state, extra)
        results = self._execute_tool_batch(tool_calls, ctx)

        new_msgs = state.get("messages", []) + [
            tool_result_message(tc["id"], results.get(tc["id"], ""))
            for tc in tool_calls
        ]

        for tc in tool_calls:
            display = _parse_tool_display(tc)
            res = results.get(tc["id"], "")
            if tc["name"] == "search_knowledge_base":
                cnt = len(_re.findall(r"【片段 \d+", res))
                if cnt:
                    display["chunks"] = cnt
            elif tc["name"] == "web_search":
                cnt = len(_re.findall(r"\[搜索结果 \d+\]", res))
                if cnt:
                    display["chunks"] = cnt
            writer({"type": "status", "status": "tool_result", **display})
            if emit:
                emit({"type": "status", "status": "tool_result", **display})

        updates = dict(state)
        updates["messages"] = new_msgs
        updates["tool_calls"] = None

        q = self._check_clarification(tool_calls)
        if q is not None:
            logger.debug("提前中断工具循环：LLM 需要澄清")
            updates["clarification"] = q
            updates["finished"] = True
            updates["next_action"] = "finish"
            self._persist_turn(updates)
            self._checkpoint(updates)
            return updates

        updates["next_action"] = "agent"
        self._persist_turn(updates)
        self._checkpoint(updates)
        return updates

    # ── 图节点：retry ──

    def _retry_node(self, state: dict, config: RunnableConfig) -> dict:
        """重试节点：补一条 user 提示后回 agent。"""
        prompt = (
            "请直接回答用户的问题，不要使用工具。"
            if state.get("retry_op") == "empty"
            else "继续，不要重复已写过的内容。"
        )
        updates = dict(state)
        updates["messages"] = state.get("messages", []) + [
            {"role": "user", "content": prompt}
        ]
        updates["retry_op"] = None
        updates["tool_calls"] = None
        updates["next_action"] = "agent"
        return updates

    # ── 顶层入口 ──

    def generate_answer(
        self,
        query,
        stream=False,
        history: list = None,
        partition: str = None,
        session_id: str = "default",
        style: str | None = None,
        workflow: str | None = None,
        cancel_check: Callable[[], bool] | None = None,
        emit_event: Callable[[dict], None] | None = None,
    ):
        """生成答案的顶层入口（非流式返回字符串；流式返回事件生成器）。

        配置热重载 → 构造初始图状态 → invoke / stream。
        """
        reload = getattr(self.cfg, "reload_if_changed", None)
        if callable(reload):
            reload()
        from .tools import registry as _reg
        _reg.reset_external_lookup_counts()
        logger.debug(f"收到用户查询: {query} (style={style}), (workflow={workflow})")

        system_msg = self._build_system_message(style=style, workflow=workflow)
        goal_line = _get_goal_line(session_id)
        if goal_line:
            system_msg += goal_line
            logger.debug(f"注入活跃目标: session={session_id[:8]}")

        messages: list = [{"role": "system", "content": system_msg}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": query})

        max_iter = getattr(self.cfg, "agent_max_tool_iter", 15)
        cw = getattr(self.cfg, "context_window_chars", None)

        mark = len(messages) - 1
        initial: GraphState = {
            "messages": messages,
            "iteration": 0,
            "max_iterations": max_iter,
            "context_window_chars": cw or 40000,
            "session_id": session_id,
            "partition": partition,
            "style": style,
            "workflow": workflow,
            "next_action": "agent",
            "tool_calls": None,
            "retry_op": None,
            "empty_retries": 0,
            "length_retries": 0,
            "clarification": None,
            "final_answer": None,
            "finished": False,
            "saved_from": mark,
            "saved_idx": mark,
        }
        config = {
            "configurable": {
                "thread_id": session_id,
                "partition": partition,
                "session_id": session_id,
                "emit_event": emit_event,
                "cancel_check": cancel_check,
            }
        }

        if stream:
            return self._stream(initial, config)
        return self._invoke(initial, config)

    # ── 执行 ──

    def _invoke(self, state: dict, config: dict) -> str:
        """非流式执行：graph.invoke → 取最终答案。"""
        try:
            final = self.graph.invoke(state, config=config)
        except Exception as e:
            logger.error(f"Agent 图执行失败: {e}", exc_info=True)
            return "抱歉，模型处理请求时发生了错误。"

        ans = final.get("final_answer") or final.get("clarification") or ""
        if not ans:
            ans = last_assistant_content(final.get("messages") or [])
        ans = ans or "抱歉，模型处理请求时发生了错误。"
        if final.get("finished"):
            self._clear_checkpoint(final)
        return ans

    def _stream(self, state: dict, config: dict):
        """流式执行：graph.stream(stream_mode="custom") → 转发事件。"""
        thread_id = state.get("session_id") or "default"

        def gen():
            reached_end = False
            try:
                for ev in self.graph.stream(state, config=config, stream_mode="custom"):
                    if isinstance(ev, dict) and ev.get("type") in ("token", "reasoning", "status"):
                        if ev.get("type") == "status" and ev.get("status") == "finished":
                            reached_end = True
                        yield ev
            except Exception as e:
                logger.error(f"Agent 流式执行失败: {e}", exc_info=True)
                yield {"type": "token", "text": "\n\n抱歉，模型处理请求时发生了错误。"}
            finally:
                if reached_end and self.checkpoint_store is not None:
                    self._clear_checkpoint({"session_id": thread_id})

        return gen()

    # ── 断点续跑 ──

    def resume_from_checkpoint(
        self,
        session_id: str,
        *,
        extra_iterations: int = 0,
        stream: bool = False,
        cancel_check: Callable[[], bool] | None = None,
        emit_event: Callable[[dict], None] | None = None,
    ):
        """从最近快照续跑（可加迭代预算）。

        Returns:
            非流式返回续跑答案字符串；流式返回事件生成器；无快照返回 None。
        """
        store = self.checkpoint_store
        if store is None:
            return None
        state = store.load(session_id)
        if not state:
            return None

        state = dict(state)
        # 归一化：清掉中转信号，让 agent 从当前消息续跑
        state["next_action"] = "agent"
        state["tool_calls"] = None
        state["retry_op"] = None
        state["clarification"] = None
        state["final_answer"] = None
        state["finished"] = False
        if extra_iterations:
            state["max_iterations"] = (state.get("max_iterations") or 0) + extra_iterations

        config = {
            "configurable": {
                "thread_id": session_id,
                "partition": state.get("partition"),
                "session_id": session_id,
                "emit_event": emit_event,
                "cancel_check": cancel_check,
            }
        }
        if stream:
            return self._stream(state, config)
        return self._invoke(state, config)
