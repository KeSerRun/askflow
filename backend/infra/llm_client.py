# ── OpenAI 客户端封装 ─────────────────────────────────────────────
"""OpenAI / 兼容 API 的统一客户端封装。

提供 Chat / Embedding / 流式 / 工具调用 等接口的单例共享客户端，
避免重复创建连接池，同时封装友好的错误分类与自动重试逻辑。
"""

import os
from typing import Generator, Iterable, List, Optional

from openai import OpenAI

from infra.logger import logger


class OpenAIClient:
    """统一封装 OpenAI 同步客户端，供 LLM / Embedding 共用一个实例。

    整个项目共享同一个客户端实例，避免重复创建连接池。
    支持标准 OpenAI API、第三方兼容 API（Azure、智谱、DeepSeek 等）。

    Attributes:
        client: OpenAI SDK 原生客户端实例。
        base_url: API 端点地址。
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = 60.0,
        max_retries: int = 3,
        client_name: str = "Chat",
        default_headers: Optional[dict] = None,
    ):
        """初始化 OpenAI 客户端。

        Args:
            api_key: API 密钥；为 None 时自动读取环境变量 LLM_API_KEY。
            base_url: 兼容第三方 API 的入口地址；为 None 则使用 openai 官方默认值。
            timeout: 请求超时秒数，默认 60s。
            max_retries: 失败自动重试次数，默认 3 次。
            client_name: 仅用于日志标识，不参与业务逻辑。
            default_headers: 附加到所有请求的默认头（如 opencode Go 的 x-opencode-session）。

        Raises:
            RuntimeError: 未设置 API 密钥时抛出。
        """
        key = api_key or os.environ.get("LLM_API_KEY")

        if not key:
            raise RuntimeError(
                "未设置 LLM_API_KEY，请在 .env 或环境变量中配置"
            )

        self.client = OpenAI(
            api_key=key,
            base_url=base_url or None,
            timeout=timeout,
            max_retries=max_retries,
            default_headers=default_headers or None,
        )

        self.base_url = base_url

        logger.debug(f"{client_name} OpenAI 客户端初始化完成，base_url={base_url or 'https://api.openai.com/v1'}")

    # ── 错误分类 ──────────────────────────────────────────────────

    @staticmethod
    def classify_error(e: Exception) -> str:
        """将 API 错误分类为用户友好的消息。

        Args:
            e: 捕获的异常对象。

        Returns:
            中文错误描述字符串。
        """
        msg = str(e)
        if "402" in msg or "Insufficient Balance" in msg or "insufficient_balance" in msg:
            return "API 余额不足，请检查账户余额或更换 API Key。"
        if "401" in msg or "Unauthorized" in msg or "invalid_api_key" in msg:
            return "API Key 无效，请在配置中检查 API Key。"
        if "429" in msg or "Rate limit" in msg or "rate_limit" in msg:
            return "API 请求频率过高，请稍后重试。"
        if "500" in msg or "502" in msg or "503" in msg or "server_error" in msg:
            return "API 服务暂时不可用，请稍后重试。"
        if "timeout" in msg.lower():
            return "API 请求超时，请检查网络连接。"
        if "model" in msg.lower() and "not found" in msg.lower():
            return f"模型不存在或不可用，请检查模型名称配置。"
        return f"LLM 调用失败: {e}"

    # ── 聊天 ──────────────────────────────────────────────────────

    def chat(
        self,
        messages: List[dict],
        model: str,
        stream: bool = False,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        reasoning_effort: Optional[str] = None,
    ):
        """发送聊天请求，支持非流式与流式两种模式。

        Args:
            messages: OpenAI 格式的消息列表。
            model: 模型名称。
            stream: 是否流式输出。
            temperature: 采样温度，默认 0.7。
            max_tokens: 最大输出 token 数。
            reasoning_effort: 推理模型 effort 参数（如 'high'）。

        Returns:
            非流式：文本字符串。
            流式：Generator[str, None, None] 逐 chunk 产出文本。
        """
        kwargs = dict(model=model, messages=messages, temperature=temperature)

        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens

        if reasoning_effort is not None:
            kwargs["reasoning_effort"] = reasoning_effort

        if not stream:

            resp = self.client.chat.completions.create(**kwargs)

            content = resp.choices[0].message.content or ""

            if not content.strip():
                logger.debug(f"LLM 返回空内容 model={model} finish_reason={resp.choices[0].finish_reason}")

            return content.strip()

        kwargs["stream"] = True

        return self._stream_chat(kwargs)

    def _stream_chat(self, kwargs: dict) -> Generator[str, None, None]:
        """流式聊天生成器 —— 逐 chunk 产出文本内容 (str)。

        Args:
            kwargs: 已包含 stream=True 的请求参数字典。

        Yields:
            每段增量文本字符串。
        """
        resp = self.client.chat.completions.create(**kwargs)

        for chunk in resp:
            if not chunk.choices:
                continue

            delta = chunk.choices[0].delta

            content = getattr(delta, "content", None)

            if content:
                yield content

    # ── 聊天（工具调用） ──────────────────────────────────────────

    def chat_with_tools(
        self,
        messages: List[dict],
        model: str,
        tools: List[dict],
        tool_choice: str = "auto",
        stream: bool = False,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        reasoning_effort: Optional[str] = None,
    ):
        """发送带工具调用的聊天请求。

        Args:
            messages: OpenAI 格式的消息列表。
            model: 模型名称。
            tools: 工具定义列表。
            tool_choice: 工具选择策略（'auto' | 'none' | 'required'）。
            stream: 是否流式输出。
            temperature: 采样温度，默认 0.7。
            max_tokens: 最大输出 token 数。
            reasoning_effort: 推理模型 effort 参数。

        Returns:
            非流式返回包含 content / reasoning_content / tool_calls / finish_reason 的 dict。
            流式返回 Generator，产出 {{"type": "content"|"tool_calls"|"reasoning"|"finish"}, ...} 事件。
        """
        kwargs = dict(
            model=model,
            messages=messages,
            temperature=temperature,
        )

        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice

        if reasoning_effort is not None:
            kwargs["reasoning_effort"] = reasoning_effort

        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens

        if not stream:

            resp = self.client.chat.completions.create(**kwargs)

            msg = resp.choices[0].message

            tool_calls = []

            for tc in (msg.tool_calls or []):
                tool_calls.append({
                    "id": tc.id,
                    "name": tc.function.name,
                    "arguments": tc.function.arguments or "",
                })

            reasoning = getattr(msg, "reasoning_content", None)
            if reasoning is None:
                extra = getattr(msg, "model_extra", None) or {}
                reasoning = extra.get("reasoning_content")
            return {
                "content": msg.content or "",
                "reasoning_content": reasoning,
                "tool_calls": tool_calls,
                "finish_reason": resp.choices[0].finish_reason or "stop",
            }

        kwargs["stream"] = True

        return self._stream_chat_with_tools(kwargs)

    def _stream_chat_with_tools(self, kwargs: dict):
        """流式对话 + 工具调用生成器 —— 逐 chunk 产出内容文本或工具调用结果。

        产出的事件格式：
            {"type": "content", "text": "..."}        — 文本片段
            {"type": "tool_calls", "calls": [...]}    — 工具调用
            {"type": "reasoning", "text": "..."}      — 推理内容
            {"type": "finish", "reason": "..."}       — 完成信号

        Args:
            kwargs: 已包含 stream=True 的请求参数字典。

        Yields:
            事件字典，调用方根据 type 字段分流处理。
        """
        resp = self.client.chat.completions.create(**kwargs)

        accumulated: dict = {}
        finish_reason: str | None = None

        try:
            for chunk in resp:
                if not chunk.choices:
                    continue

                choice = chunk.choices[0]

                delta = choice.delta

                content = getattr(delta, "content", None)
                if content:
                    yield {"type": "content", "text": content}

                reasoning = getattr(delta, "reasoning_content", None)
                if reasoning is None:
                    extra = getattr(delta, "model_extra", None) or {}
                    reasoning = extra.get("reasoning_content")
                if reasoning:
                    yield {"type": "reasoning", "text": reasoning}

                tc_deltas = getattr(delta, "tool_calls", None)
                if tc_deltas:
                    for i, tcd in enumerate(tc_deltas):

                        idx = getattr(tcd, "index", i)

                        acc = accumulated.setdefault(idx, {"id": "", "name": "", "arguments": ""})

                        if getattr(tcd, "id", None):
                            acc["id"] = tcd.id

                        fn = getattr(tcd, "function", None)
                        if fn is not None:
                            if getattr(fn, "name", None):
                                acc["name"] = fn.name
                            if getattr(fn, "arguments", None):
                                acc["arguments"] += fn.arguments

                finish_reason = getattr(choice, "finish_reason", None)

                if finish_reason == "tool_calls" and accumulated:
                    yield {"type": "tool_calls", "calls": list(accumulated.values())}
                    accumulated.clear()

        finally:

            if accumulated:
                yield {"type": "tool_calls", "calls": list(accumulated.values())}

            if finish_reason:
                yield {"type": "finish", "reason": finish_reason}

    # ── 嵌入 ──────────────────────────────────────────────────────

    def embed(
        self,
        texts: Iterable[str],
        model: str,
        batch_size: int = 32,
    ) -> List[List[float]]:
        """批量文本嵌入，支持自动分批。

        Args:
            texts: 待嵌入的文本可迭代对象。
            model: 嵌入模型名称。
            batch_size: 每批处理的文本数，默认 32。

        Returns:
            嵌入向量列表，每项为 float 列表。

        Raises:
            嵌入失败时向上抛出原始异常。
        """
        texts = list(texts)

        if not texts:
            return []

        total = len(texts)

        num_batches = (total + batch_size - 1) // batch_size

        out: List[List[float]] = []

        for i in range(0, total, batch_size):
            batch = texts[i: i + batch_size]

            batch_idx = i // batch_size + 1

            logger.debug(f"嵌入请求 {batch_idx}/{num_batches} (本批 {len(batch)} 条, 累计 {i}/{total})...")

            kwargs = dict(model=model, input=batch)

            try:
                resp = self.client.embeddings.create(**kwargs)

                out.extend([d.embedding for d in resp.data])

                logger.debug(f"嵌入完成 {batch_idx}/{num_batches} (本批 {len(batch)} 条)")

            except Exception as e:
                logger.error(f"嵌入失败 {batch_idx}/{num_batches}: {e}")

                raise

        return out