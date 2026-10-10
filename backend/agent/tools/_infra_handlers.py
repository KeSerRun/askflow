"""基础设施工具 handlers：澄清 / 会话目标 / 运行时状态 / 工作流读取。

注册统一在 registry.py 的 register_all_builtins() 中完成。
"""

from __future__ import annotations

from .registry import ToolContext

# ── 便利工具：向用户询问 ──


def _exec_ask_clarification(args: dict, ctx: ToolContext) -> str:
    """向用户发起澄清询问。

    当用户请求模糊（指代不清、未指定具体文档）、且已有检索结果不足以推断时调用。
    调用后会中断对话流，将 question 抛给用户等待补充。

    Args:
        args: 工具参数字典，键:
            question: 向用户询问的具体问题（必填）。
        ctx: 工具运行时上下文。

    Returns:
        用户需要看到的询问文本。
    """
    question = args.get("question", "需要您提供更多信息。")
    return question


# ── 运行时状态查询 ──


def _exec_my(args: dict, ctx: ToolContext) -> str:
    """查询运行时状态和配置项。

    支持查看完整状态概览与特定配置项。
    由 LLM 在需要了解自身运行环境时调用。

    Args:
        args: 工具参数字典，键:
            action: 操作类型 — 'check'（查看状态）。
            key: 要查看的特定配置项关键词（可选）。
        ctx: 工具运行时上下文。

    Returns:
        格式化的状态文本或错误提示。
    """
    action = args.get("action", "check")
    key = args.get("key", "")

    from . import registry
    from ._common import _cfg

    if action == "check" and not key:
        lines = ["=== 当前状态 ==="]
        lines.append(f"模型: {_cfg(ctx, 'llm_model', '-')}")
        lines.append(f"最大迭代: {_cfg(ctx, 'agent_max_tool_iter', '-')}")
        lines.append(f"上下文窗口: {_cfg(ctx, 'context_window_chars', '-')} 字符")
        lines.append(f"输出字符上限: {_cfg(ctx, 'agent_max_output_chars', '-')}")
        lines.append(f"检索 Top-K: {_cfg(ctx, 'retrieval_top_k', '-')}")
        lines.append(f"搜索后端: {_cfg(ctx, 'search_backend', '-')}")
        lines.append("")

        counts = dict(registry.call_counts)
        if counts:
            lines.append("=== 工具调用统计 ===")
            for name, cnt in sorted(counts.items(), key=lambda x: -x[1]):
                lines.append(f"  {name}: {cnt}")

        return "\n".join(lines)

    elif action == "check" and key:
        key_map = {
            "model": ("llm_model", _cfg(ctx, "llm_model", "-")),
            "max_iterations": ("agent_max_tool_iter", _cfg(ctx, "agent_max_tool_iter", "-")),
            "context_window": ("context_window_chars", _cfg(ctx, "context_window_chars", "-")),
            "max_tokens": ("agent_max_output_chars", _cfg(ctx, "agent_max_output_chars", "-")),
            "retrieval_top_k": ("retrieval_top_k", _cfg(ctx, "retrieval_top_k", "-")),
        }
        if key in key_map:
            name, val = key_map[key]
            return f"{name}: {val}"
        return f"(未知配置: {key})"

    return "(未知 action)"


# ── 会话目标管理 ──

_GOAL_CACHE: dict[str, str] = {}  # session_id → goal 文本


def _exec_set_goal(args: dict, ctx: ToolContext) -> str:
    """设置会话持续目标，仅存内存缓存。

    当用户交代了一个多轮对话才能完成的目标时调用。
    目标信息会持续注入 system prompt 供后续对话参考。

    Args:
        args: 工具参数字典，键:
            goal: 目标的详细描述（必填）。
        ctx: 工具运行时上下文。

    Returns:
        操作结果提示字符串。
    """
    goal = (args.get("goal") or "").strip()
    if not goal:
        return "(未提供 goal 参数)"
    sid = ctx.session_id or ""
    _GOAL_CACHE[sid] = goal
    return f"(目标已设置：{goal})"


def _exec_complete_goal(args: dict, ctx: ToolContext) -> str:
    """完成当前目标。

    当用户确认目标已完成时调用。从缓存中移除该目标。

    Args:
        args: 工具参数字典（本工具无需额外参数）。
        ctx: 工具运行时上下文。

    Returns:
        操作结果提示字符串。
    """
    sid = ctx.session_id or ""
    _GOAL_CACHE.pop(sid, None)
    return "(当前目标已完成)"


def _get_goal_line(sid: str) -> str:
    """读取当前活跃目标文本，仅查内存缓存。

    用于组装 system prompt 中的目标信息行。

    Args:
        sid: 会话 ID。

    Returns:
        格式如 '\\n# 当前目标：xxx' 的字符串，无活跃目标时返回空字符串。
    """
    goal = _GOAL_CACHE.get(sid)
    if goal:
        return f"\n# 当前目标：{goal}"
    return ""


# ── 工作流读取 ──


def _exec_read_workflow(args: dict, ctx: ToolContext) -> str:
    """读取工作流的完整分步指令。

    system prompt 中列出了可用的工作流及其摘要。
    如需使用某个工作流，先调用此工具获取完整指令，再按步骤执行。

    Args:
        args: 工具参数字典，键:
            name: 工作流名称，如 USstocks、Autoplan、DeepResearch（必填）。
        ctx: 工具运行时上下文。

    Returns:
        工作流完整指令文本，或错误提示。
    """
    name = (args.get("name") or "").strip()
    if not name:
        return "(未提供 name 参数)"
    router = getattr(ctx, "workflow_router", None)
    if not router:
        return "(工作流路由器不可用)"
    content = router.get_workflow_content(name)
    if not content:
        return f"(未找到工作流: {name})"
    return f"工作流：{name}\n\n{content}"
