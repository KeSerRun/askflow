"""agent.tools._web_handlers —— 工具 handler 实现（@tool 声明 + langchain 类型签名推导；辅助函数在 _common）。"""
from __future__ import annotations

import re as _re
from datetime import datetime as _dt
from typing import Annotated

from pydantic import Field

from infra.util.logger import logger

from ._common import (
    _cache_get,
    _cache_set,
    _cfg,
    _search_searxng,
    _try_jina_reader,
    _try_raw_html,
    _try_readability,
    _validate_url_chain,
)
from ._context import current_tool_ctx, tool


@tool('read_url')
def _exec_read_url(
    url: Annotated[str, Field(description="要读取的网页完整 URL")],
    offset: Annotated[int | None, Field(description="读取起始偏移，用于分页续读")] = None,
    max_chars: Annotated[int | None, Field(description="本次最多读取字符数")] = None,
) -> str:
    """抓取指定 URL 并提取可读正文（自动去除广告/导航），支持 offset/max_chars 分页续读，含重定向链 SSRF 防护。

    url 需为 http(s):// 开头的完整地址；常配合 web_search 的结果链接使用。
    """
    ctx = current_tool_ctx()
    url = (url or "").strip()
    if not url:
        return "(未提供 URL 参数)"

    offset = offset or 0
    max_chars = max_chars or _cfg(ctx, "context_tool_page_chars", 5000)

    logger.debug(f"tool read_url: 开始抓取 {url} (offset={offset}, max_chars={max_chars})")

    final_url, error = _validate_url_chain(url)
    if error:
        logger.warning(f"tool read_url 被 SSRF 防护拦截: {error}")
        return f"({error})"

    target = final_url or url

    result = _cache_get(ctx, target)
    if result is None:
        result = _try_jina_reader(target, jina_key=_cfg(ctx, "jina_api_key", ""))
        if not result:
            result = _try_readability(target)
        if not result:
            result = _try_raw_html(target)
        if result:
            _cache_set(ctx, target, result)

    if not result:
        return f"(读取网页失败: {target})"

    total = len(result)
    if offset >= total:
        return f"(偏移 {offset} 超出内容长度 {total}，已无更多内容)"

    page = result[offset:offset + max_chars]
    next_offset = offset + max_chars

    logger.debug(f"tool read_url 成功: {target} (返回 {len(page)}/{total} 字符)")
    more = f"（还有更多内容，可继续调用 read_url 传入 offset={next_offset} 读取下一页）" if next_offset < total else ""

    head = "" if offset == 0 else f"（第 {offset} 字符起，共 {total} 字符）\n"

    return head + page + (f"\n\n{more}" if more else "")


@tool('web_search')
def _exec_web_search(
    query: Annotated[str, Field(description="搜索关键词")],
    max_results: Annotated[int, Field(description="返回结果数，上限 10")] = 5,
) -> str:
    """联网实时搜索（SearXNG），自动补充当前年份，返回标题、摘要与链接。

    用于时事/最新信息或模型知识之外的内容；拿到链接后可再用 read_url 读正文。
    """
    ctx = current_tool_ctx()
    query = (query or "").strip()
    if not query:
        return "(未提供搜索 query)"
    max_results = min(int(max_results), 10)

    logger.debug(f"tool web_search query={query!r} max={max_results}")

    _now = _dt.now()
    if not _re.search(r'(?<!\d)(?:19|20)\d{2}(?!\d)', query):
        query = f"{_now.year}年 {query}"
        logger.debug(f"tool web_search 已补年份: {query!r}")

    results = _search_searxng(
        query, max_results,
        searxng_url=_cfg(ctx, "search_searxng_url", ""),
        timeout=_cfg(ctx, "search_timeout", 10),
    )

    if results is None:
        return "(联网搜索暂时不可用，请直接回答，不要重试。)"
    if not results:
        return "(未找到相关搜索结果)"

    lines = []
    for i, r in enumerate(results, 1):
        title = r.get("title", "").strip()
        snippet = r.get("body", "").strip()
        url = r.get("href", "").strip()
        lines.append(f"[搜索结果 {i}] {title}")
        if snippet:
            lines.append(f"   {snippet}")
        if url:
            lines.append(f"   {url}")
        lines.append("")

    output = "\n".join(lines).strip()
    logger.debug(f"tool web_search 返回 {len(results)} 条结果, 长度={len(output)}")
    return output
