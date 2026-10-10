"""adapters.llm —— LLM 对话/嵌入的 Ports 实现。

复用现有 base.llm_client.OpenAIClient 作为底层传输，
对外暴露 ports.ChatModel 与 ports.Embedder 契约。
"""

from .openai import OpenAIChatModel, OpenAIEmbedder  # noqa: F401

__all__ = ["OpenAIChatModel", "OpenAIEmbedder"]