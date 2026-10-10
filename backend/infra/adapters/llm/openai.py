"""adapters.llm.openai —— OpenAI 兼容端点适配器。

OpenAIChatModel : 对话（函数调用 + 流式）→ ports.ChatModel
OpenAIEmbedder  : 文本嵌入 → ports.Embedder

底层复用 base.llm_client.OpenAIClient（支持 OpenAI / SiliconFlow / 任意兼容端点）。
"""

from __future__ import annotations

from typing import Iterator, Optional

from infra.llm_client import OpenAIClient

from core.models import ChatResponse, ChatStreamEvent


class OpenAIChatModel:
    """对话模型适配器。"""

    def __init__(self, client: OpenAIClient, model: str):
        """初始化。

        Args:
            client: 已配置连接参数的底层客户端。
            model: 模型名（如 deepseek-v4-flash）。
        """
        self._client = client
        self._model = model

    def chat(
        self,
        messages: list[dict],
        *,
        tools: Optional[list[dict]] = None,
        tool_choice: str = "auto",
        temperature: float = 0.7,
        max_tokens: int = 8192,
        reasoning_effort: Optional[str] = None,
    ) -> ChatResponse:
        resp = self._client.chat_with_tools(
            messages=messages,
            model=self._model,
            tools=tools or [],
            tool_choice=tool_choice,
            stream=False,
            temperature=temperature,
            max_tokens=max_tokens,
            reasoning_effort=reasoning_effort,
        )
        return ChatResponse(
            content=resp.get("content") or "",
            tool_calls=resp.get("tool_calls") or [],
            finish_reason=resp.get("finish_reason"),
        )

    def chat_stream(
        self,
        messages: list[dict],
        *,
        tools: Optional[list[dict]] = None,
        tool_choice: str = "auto",
        temperature: float = 0.7,
        max_tokens: int = 8192,
        reasoning_effort: Optional[str] = None,
    ) -> Iterator[ChatStreamEvent]:
        for ev in self._client.chat_with_tools(
            messages=messages,
            model=self._model,
            tools=tools or [],
            tool_choice=tool_choice,
            stream=True,
            temperature=temperature,
            max_tokens=max_tokens,
            reasoning_effort=reasoning_effort,
        ):
            etype = ev.get("type", "")
            if etype == "tool_calls":
                yield ChatStreamEvent.tool_calls(ev.get("calls") or [])
            elif etype == "finish":
                yield ChatStreamEvent.finish(ev.get("reason"))
            elif etype == "reasoning":
                yield ChatStreamEvent.reasoning(ev.get("text") or "")
            else:  # content / default
                yield ChatStreamEvent.content(ev.get("text") or "")


class OpenAIEmbedder:
    """文本嵌入适配器。"""

    def __init__(self, client: OpenAIClient, model: str, dimension: int):
        """初始化。

        Args:
            client: 已配置连接参数的底层客户端。
            model: 嵌入模型名（如 BAAI/bge-m3）。
            dimension: 向量维度（如 1024）。
        """
        self._client = client
        self._model = model
        self._dimension = dimension

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return self._client.embed(texts, model=self._model)