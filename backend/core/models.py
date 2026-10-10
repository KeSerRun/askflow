"""core.models —— 跨层共享的纯数据类型。

只保留**被多个层共同使用**的类型（Document / ChatResponse / ChatStreamEvent）；
单层专用类型下沉在各自适配器（adapters.pdf / adapters.queue）。
本模块不含任何框架/存储/HTTP 依赖。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class Document:
    """一个可入库/检索的文档片段。

    Attributes:
        page_content: 片段正文。
        metadata: 任意元数据（source/partition/chunk_type/page 等）。
    """

    page_content: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ChatResponse:
    """LLM 单轮对话返回值（非流式）。

    Attributes:
        content: 最终文本（工具调用场景可同时包含 tool_calls）。
        tool_calls: 模型请求的工具调用列表（OpenAI 兼容格式 dict）。
        finish_reason: 结束原因（stop/length/tool_calls）。
    """

    content: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    finish_reason: Optional[str] = None


@dataclass
class ChatStreamEvent:
    """LLM 流式事件（与 HTTP/SSE 解耦的中间表示）。

    Attributes:
        type: content / reasoning / tool_calls / finish。
        text: 文本增量（type=content|reasoning 时）。
        calls: 工具调用列表（type=tool_calls 时）。
        reason: finish 原因（type=finish 时）。
    """

    type: str
    text: str = ""
    calls: list[dict] = field(default_factory=list)
    reason: Optional[str] = None

    @classmethod
    def content(cls, text: str) -> "ChatStreamEvent":
        return cls(type="content", text=text)

    @classmethod
    def reasoning(cls, text: str) -> "ChatStreamEvent":
        return cls(type="reasoning", text=text)

    @classmethod
    def tool_calls(cls, calls: list[dict]) -> "ChatStreamEvent":
        return cls(type="tool_calls", calls=calls)

    @classmethod
    def finish(cls, reason: Optional[str] = None) -> "ChatStreamEvent":
        return cls(type="finish", reason=reason)
