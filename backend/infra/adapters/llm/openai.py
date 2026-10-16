"""adapters.llm.openai —— OpenAI 兼容端点适配器（直连 SDK）。

OpenAIChatModel : 对话（函数调用 + 流式）→ ports.ChatModel
OpenAIEmbedder  : 文本嵌入（自动分批）  → ports.Embedder

直接封装 `openai.OpenAI` 客户端（支持 OpenAI / SiliconFlow / 任意兼容端点），
不再引入独立的传输层；原始 SDK 结果在本类内直接转成领域类型
（ChatResponse / ChatStreamEvent）。
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterable, Iterator

from openai import OpenAI

from core.models import ChatResponse, ChatStreamEvent
from infra.util.logger import logger

# 思考内容的字段名：DeepSeek-R1 用 ``reasoning_content``，Ollama(Qwen3) 用 ``reasoning``
_REASONING_FIELDS = ("reasoning_content", "reasoning")

# 端点专属默认头：命中 base_url 标记时注入对应请求头（值自动生成）。
# 把 provider 细节收敛在适配器内，组合根无需认识各 provider。
_PROVIDER_HEADERS: tuple[tuple[str, str], ...] = (
    ("opencode", "x-opencode-session"),   # opencode Go 端点要求会话头用于路由
)


def resolve_default_headers(base_url: str | None) -> dict:
    """按端点归属推断需附加的默认请求头。

    命中 ``_PROVIDER_HEADERS`` 的标记则返回对应头（会话头取随机 hex），否则返回
    空 dict。这样端点私货留在适配器内，组合根保持 provider 无关。
    """
    host = (base_url or "").lower()
    return {
        header: uuid.uuid4().hex
        for marker, header in _PROVIDER_HEADERS
        if marker in host
    }


def _delta_field(delta, *names: str) -> str | None:
    """读取流式 delta 的字段值。

    兼容 OpenAI SDK 的两种承载方式：直接属性（``delta.x``）与 ``delta.model_extra['x']``
    （SDK 未知字段的落点）。按 ``names`` 顺序返回首个非空值，都没有则 None。
    """
    extra = getattr(delta, "model_extra", None) or {}
    for name in names:
        value = extra.get(name) or getattr(delta, name, None)
        if value:
            return value
    return None


class OpenAIChatModel:
    """OpenAI 兼容对话模型适配器（ports.ChatModel）。"""

    def __init__(
        self,
        api_key: str | None,
        base_url: str | None,
        model: str,
        *,
        timeout: float = 60.0,
        max_retries: int = 3,
        default_headers: dict | None = None,
    ):
        """初始化。

        Args:
            api_key: API 密钥；为 None 时回退环境变量 LLM_API_KEY。
            base_url: 兼容端点地址；None 用 OpenAI 官方默认。
            model: 模型名（如 deepseek-v4-flash）。
            timeout: 请求超时秒数。
            max_retries: SDK 失败自动重试次数。
            default_headers: 显式默认头；None 时按端点自动推断（见 resolve_default_headers）。

        Raises:
            RuntimeError: 未提供 API 密钥时抛出。
        """
        key = api_key or os.environ.get("LLM_API_KEY")
        if not key:
            raise RuntimeError("未设置 LLM_API_KEY，请在 .env 或环境变量中配置")

        headers = (
            default_headers if default_headers is not None
            else resolve_default_headers(base_url)
        )
        self._client = OpenAI(
            api_key=key,
            base_url=base_url or None,
            timeout=timeout,
            max_retries=max_retries,
            default_headers=headers or None,
        )
        self._model = model
        logger.debug(f"Chat OpenAI 客户端初始化完成，base_url={base_url or 'https://api.openai.com/v1'}")

    def chat(
        self,
        messages: list[dict],
        *,
        tools: list[dict] | None = None,
        tool_choice: str = "auto",
        temperature: float = 0.3,
        max_tokens: int = 8192,
        reasoning_effort: str | None = None,
    ) -> ChatResponse:
        """非流式对话（支持工具调用）。"""
        kwargs: dict = dict(
            model=self._model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice
        if reasoning_effort is not None:
            kwargs["reasoning_effort"] = reasoning_effort

        resp = self._client.chat.completions.create(**kwargs)
        msg = resp.choices[0].message

        tool_calls = [
            {
                "id": tc.id,
                "name": tc.function.name,
                "arguments": tc.function.arguments or "",
            }
            for tc in (msg.tool_calls or [])
        ]
        return ChatResponse(
            content=msg.content or "",
            tool_calls=tool_calls,
            finish_reason=resp.choices[0].finish_reason or "stop",
        )

    def chat_stream(
        self,
        messages: list[dict],
        *,
        tools: list[dict] | None = None,
        tool_choice: str = "auto",
        temperature: float = 0.3,
        max_tokens: int = 8192,
        reasoning_effort: str | None = None,
    ) -> Iterator[ChatStreamEvent]:
        """流式对话（支持工具调用），产出领域事件 ChatStreamEvent。"""
        kwargs: dict = dict(
            model=self._model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
        )
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice
        if reasoning_effort is not None:
            kwargs["reasoning_effort"] = reasoning_effort

        resp = self._client.chat.completions.create(**kwargs)

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
                    yield ChatStreamEvent.content(content)

                # 思考内容（thinking 模型）：字段名兼容 reasoning_content / reasoning
                reasoning = _delta_field(delta, *_REASONING_FIELDS)
                if reasoning:
                    yield ChatStreamEvent.reasoning(reasoning)

                for i, tcd in enumerate(getattr(delta, "tool_calls", None) or []):
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
                    yield ChatStreamEvent.tool_calls(list(accumulated.values()))
                    accumulated.clear()
        finally:
            if accumulated:
                yield ChatStreamEvent.tool_calls(list(accumulated.values()))
            if finish_reason:
                yield ChatStreamEvent.finish(finish_reason)


class OpenAIEmbedder:
    """OpenAI 兼容文本嵌入适配器（ports.Embedder），自动分批。"""

    def __init__(
        self,
        api_key: str | None,
        base_url: str | None,
        model: str,
        dimension: int,
        *,
        timeout: float = 60.0,
        max_retries: int = 3,
    ):
        """初始化。

        Args:
            api_key: API 密钥；为 None 时回退 EMBED_API_KEY / LLM_API_KEY。
            base_url: 兼容端点地址。
            model: 嵌入模型名（如 OFA-Sys/chinese-clip-vit-base-patch16）。
            dimension: 向量维度（如 512）。
            timeout: 请求超时秒数。
            max_retries: SDK 失败自动重试次数。

        Raises:
            RuntimeError: 未提供 API 密钥时抛出。
        """
        key = api_key or os.environ.get("EMBED_API_KEY") or os.environ.get("LLM_API_KEY")
        if not key:
            raise RuntimeError("未设置 EMBED_API_KEY，请在 .env 或环境变量中配置")

        self._client = OpenAI(
            api_key=key,
            base_url=base_url or None,
            timeout=timeout,
            max_retries=max_retries,
        )
        self._model = model
        self._dimension = dimension

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed(self, texts: Iterable[str], batch_size: int = 32) -> list[list[float]]:
        """批量文本嵌入，自动分批。

        Args:
            texts: 待嵌入文本。
            batch_size: 每批条数（默认 32）。

        Returns:
            嵌入向量列表。
        """
        texts = list(texts)
        if not texts:
            return []

        total = len(texts)
        num_batches = (total + batch_size - 1) // batch_size
        out: list[list[float]] = []

        for i in range(0, total, batch_size):
            batch = texts[i: i + batch_size]
            batch_idx = i // batch_size + 1
            logger.debug(f"嵌入请求 {batch_idx}/{num_batches} (本批 {len(batch)} 条, 累计 {i}/{total})...")
            try:
                resp = self._client.embeddings.create(model=self._model, input=batch)
                out.extend([d.embedding for d in resp.data])
                logger.debug(f"嵌入完成 {batch_idx}/{num_batches} (本批 {len(batch)} 条)")
            except Exception as e:
                logger.error(f"嵌入失败 {batch_idx}/{num_batches}: {e}")
                raise

        return out

    def embed_image(self, data: bytes) -> list[float]:
        """图片嵌入（CLIP 图向量，与文本同一向量空间）。

        Args:
            data: 图片字节（PNG/JPEG 等）。

        Returns:
            归一化向量（与文本嵌入同维度）。

        Raises:
            RuntimeError: 图片嵌入服务不可用或编码失败。
        """
        import base64 as _b64

        import httpx

        base = str(getattr(self._client, "base_url", "") or "").rstrip("/")
        url = f"{base}/image_embeddings"
        payload = {"images": [_b64.b64encode(data).decode("ascii")]}
        try:
            resp = httpx.post(url, json=payload, timeout=60)
            resp.raise_for_status()
            items = resp.json().get("data") or []
            if not items:
                raise RuntimeError("图片嵌入返回空")
            return [float(x) for x in items[0]["embedding"]]
        except Exception as e:  # noqa: BLE001
            logger.error(f"图片嵌入失败: {e}")
            raise RuntimeError(f"图片嵌入失败: {e}") from e
