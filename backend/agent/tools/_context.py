"""agent.tools._context —— 工具运行时注入：ToolContext 上下文 + langchain BaseTool 适配。

handler 由 ``@tool`` 装饰（本模块的薄封装，签名即工具参数）；运行期 ``registry.dispatch`` 把
ToolContext 通过 ``_TOOL_CTX`` 注入当前（线程）上下文，handler 用 ``current_tool_ctx()`` 取；
``make_runtime_handler`` 把 BaseTool 适配成注册表统一签名 ``(args: dict, ctx) -> str``。
"""

from __future__ import annotations

import contextvars

from langchain_core.tools import tool as _langchain_tool

_TOOL_CTX: contextvars.ContextVar = contextvars.ContextVar("agent_tool_ctx", default=None)


def current_tool_ctx():
    """handler 内部读取当前 ToolContext（由 registry.dispatch 设置）。"""
    return _TOOL_CTX.get()


def _apply_tag(langchain_tool, tag: dict):
    """把标签合并进 BaseTool.metadata（工具自身属性，不进 LLM schema、不发给 provider）。"""
    langchain_tool.metadata = {**(langchain_tool.metadata or {}), **tag}
    return langchain_tool


def tool(
    name_or_callable=None,
    *,
    description=None,
    return_direct: bool = False,
    args_schema=None,
    infer_schema: bool = True,
    response_format: str = "content",
    parse_docstring: bool = False,
    error_on_invalid_docstring: bool = True,
    extras: dict | None = None,
    concurrent_safe: bool = False,
):
    """langchain ``@tool`` 的薄封装：额外支持 ``concurrent_safe`` 标签。

    用法与 langchain 一致：``@tool``、``@tool('name')``、``@tool('name', ...)``。
    区别：装饰完会把 ``concurrent_safe`` 写进工具的 ``.metadata["concurrency_safe"]``，
    由 ``collect_tools`` 读取并登记并发安全名单（种子入 DB → 运行时按 DB 决定分批）。

    Args:
        concurrent_safe: 是否可与其他工具并行执行（仅限只读、无副作用、结果确定的工具）。
        （其余参数与 langchain ``tool()`` 完全一致。）

    Returns:
        裸 ``@tool`` 用法直接返回 BaseTool；``@tool('name')`` 用法返回装饰器。
    """

    def _langchain_kwargs() -> dict:
        return {
            "description": description,
            "return_direct": return_direct,
            "args_schema": args_schema,
            "infer_schema": infer_schema,
            "response_format": response_format,
            "parse_docstring": parse_docstring,
            "error_on_invalid_docstring": error_on_invalid_docstring,
            "extras": extras,
        }

    if name_or_callable is not None and callable(name_or_callable) and hasattr(name_or_callable, "__name__"):
        # 裸 @tool —— langchain 直接返回 BaseTool，打上标签即返回
        _bt = _langchain_tool(name_or_callable, **_langchain_kwargs())
        return _apply_tag(_bt, {"concurrency_safe": bool(concurrent_safe)})

    # @tool('name') / @tool(...) —— langchain 返回 _tool_factory 装饰器，
    # 包一层：在拿到 BaseTool 之后打标签再返回
    _factory = _langchain_tool(name_or_callable, **_langchain_kwargs())

    def _decorate(fn):
        return _apply_tag(_factory(fn), {"concurrency_safe": bool(concurrent_safe)})

    return _decorate


def make_runtime_handler(langchain_tool):
    """把 langchain BaseTool 适配为统一签名 ``(args: dict, ctx) -> str``。"""

    def _h(args: dict, ctx) -> str:
        _TOOL_CTX.set(ctx)
        try:
            result = langchain_tool.invoke(dict(args or {}))
        finally:
            _TOOL_CTX.set(None)
        return result if isinstance(result, str) else str(result or "")

    return _h
