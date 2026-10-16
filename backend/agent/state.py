"""Agent 图状态（LangGraph typed state）——替代旧 dataclass AgentState。

所有字段均为 JSON 可序列化（含 checkpoint 持久化）；运行时注入项
（cancel_check / emit_event）**不进状态**，走 ``config["configurable"]``。
"""

from __future__ import annotations

from typing import TypedDict

from .tokens import estimate_messages_tokens


class GraphState(TypedDict, total=False):
    """LangGraph 共享状态。"""

    messages: list[dict]
    iteration: int
    max_iterations: int
    context_window_tokens: int
    session_id: str
    partition: str | None
    style: str | None
    workflow: str | None

    # 节点间路由信号
    next_action: str            # "agent" | "tools" | "retry" | "finish"
    tool_calls: list[dict] | None
    retry_op: str | None     # "empty" | "continue"
    empty_retries: int
    length_retries: int
    clarification: str | None
    clarification_options: list | None
    final_answer: str | None
    finished: bool | None

    # 历史增量持久化游标
    saved_from: int
    saved_idx: int


def total_message_tokens(state: dict) -> int:
    """估算 messages 总 token（不含 system 消息）。"""
    return estimate_messages_tokens(state.get("messages", []))


def budget_ok(state: dict) -> bool:
    """迭代次数与上下文窗口均未超限才可继续。"""
    max_iter = state.get("max_iterations") or 15
    if (state.get("iteration") or 0) >= max_iter:
        return False
    window = state.get("context_window_tokens") or 128000
    return total_message_tokens(state) <= window


def assistant_message(content: str, tool_calls: list[dict] | None = None) -> dict:
    """构造 assistant 消息（带或不带 tool_calls）。"""
    if tool_calls:
        return {
            "role": "assistant",
            "content": content,
            "tool_calls": [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {"name": tc["name"], "arguments": tc["arguments"]},
                }
                for tc in tool_calls
            ],
        }
    return {"role": "assistant", "content": content}


def tool_result_message(tool_call_id: str, content: str) -> dict:
    """构造 tool 结果消息。"""
    return {"role": "tool", "tool_call_id": tool_call_id, "content": content}


def last_assistant_content(messages: list[dict]) -> str:
    """取最后一条 assistant 消息的正文（无则空串）。"""
    for m in reversed(messages or []):
        if m.get("role") == "assistant":
            return m.get("content") or ""
    return ""
