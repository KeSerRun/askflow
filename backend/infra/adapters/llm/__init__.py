"""adapters.llm —— LLM 对话/嵌入的 Ports 实现。

直接封装 OpenAI SDK（支持 OpenAI / SiliconFlow / 任意兼容端点），
对外暴露 ports.ChatModel 与 ports.Embedder 契约。
"""

from .openai import OpenAIChatModel, OpenAIEmbedder  # noqa: F401

__all__ = ["OpenAIChatModel", "OpenAIEmbedder"]