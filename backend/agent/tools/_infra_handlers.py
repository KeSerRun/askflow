"""agent.tools._infra_handlers —— 工具 handler 实现（@tool 声明 + langchain 类型签名推导；辅助函数在 _common）。"""
from __future__ import annotations

from typing import Annotated

from pydantic import Field

from ._common import _GOAL_CACHE, _check_todo, _get_todolist, _set_todolist
from ._context import current_tool_ctx, tool


@tool('ask_user_for_clarification')
def _exec_ask_clarification(
    question: Annotated[str, Field(description="向用户询问的具体问题")],
    options: Annotated[list[str] | None,
                       Field(description="给用户的选择项（3-5 个建议答案，前端以选择框呈现并含自定义输入），"
                                         "可省略")] = None,
) -> str:
    """当需求缺少关键信息、或存在多种合理理解而无法自行决定时，向用户提出一个明确问题并给出 3-5 个建议选项。

    前端以选择框 + 自定义输入呈现，用户回答后再继续；可自行合理假设时不要用。
    """
    picks = "\n".join(f"- {o}" for o in (options or []) if str(o).strip())
    base = f"(需要向用户澄清：{question}"
    if picks:
        return f"{base}\n可选项：\n{picks})"
    return f"{base})"


@tool('my')
def _exec_my(
    action: Annotated[str, Field(description="操作类型：'check' 查看状态")],
    key: Annotated[str | None, Field(description="要查看的配置项关键词，可省")] = None,
) -> str:
    """查看自身运行状态与关键配置（当前模型、最大迭代、上下文窗口、输出上限、检索 Top-K、搜索后端与工具调用统计）。

    用于自检或回答“你用的是什么模型”之类问题。
    """
    ctx = current_tool_ctx()
    action = action
    key = key

    from . import registry
    from ._common import _cfg

    if action == "check" and not key:
        lines = ["=== 当前状态 ==="]
        lines.append(f"模型: {_cfg(ctx, 'llm_model', '-')}")
        lines.append(f"最大迭代: {_cfg(ctx, 'agent_max_tool_iter', '-')}")
        lines.append(f"上下文窗口: {_cfg(ctx, 'context_window_tokens', '-')} token")
        lines.append(f"输出 token 上限: {_cfg(ctx, 'agent_max_output_tokens', '-')}")
        lines.append(f"检索 Top-K: {_cfg(ctx, 'retrieval_top_k', '-')}")
        lines.append(f"搜索后端: SearXNG ({_cfg(ctx, 'search_searxng_url', '-')})")
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
            "context_window": ("context_window_tokens", _cfg(ctx, "context_window_tokens", "-")),
            "max_tokens": ("agent_max_output_tokens", _cfg(ctx, "agent_max_output_tokens", "-")),
            "retrieval_top_k": ("retrieval_top_k", _cfg(ctx, "retrieval_top_k", "-")),
        }
        if key in key_map:
            name, val = key_map[key]
            return f"{name}: {val}"
        return f"(未知配置: {key})"

    return "(未知 action)"


@tool('set_goal')
def _exec_set_goal(
    goal: Annotated[str, Field(description="目标的详细描述")],
) -> str:
    """为当前会话设置一个持续目标（内存态），后续对话围绕它展开；重复调用会覆盖旧目标。适合用户交代需要多轮完成的长期目标时。"""
    ctx = current_tool_ctx()
    goal = (goal or "").strip()
    if not goal:
        return "(未提供 goal 参数)"
    sid = ctx.session_id or ""
    _GOAL_CACHE[sid] = goal
    return f"(目标已设置：{goal})"


@tool('complete_goal')
def _exec_complete_goal() -> str:
    """清除当前会话的持续目标（表示已完成）。仅在该目标确实达成、不再需要延续时调用。"""
    ctx = current_tool_ctx()
    sid = ctx.session_id or ""
    _GOAL_CACHE.pop(sid, None)
    return "(当前目标已完成)"


@tool('set_todolist')
def _exec_set_todolist(
    items: Annotated[list[dict], Field(
        description=("规划期任务清单，覆盖旧清单。元素为 {'id': 唯一标识, 'text': 任务描述}，"
                     "按执行顺序排列，通常 3-8 项。执行阶段每完成一项调用 check_todo 勾选。")
    )] = [],
) -> str:
    """为复杂任务建立/覆盖一份可勾选的任务清单（规划阶段用）；items 为按执行顺序的 3-8 项 {'id','text'}。

    执行阶段每完成一项调用 check_todo 勾选，全部完成后汇报结果。
    """
    ctx = current_tool_ctx()
    lst = _set_todolist(ctx.session_id or "", items or [])
    if not lst:
        return "(未提供有效任务清单)"
    lines = [f"- [{'x' if it['done'] else ' '}] ({it['id']}) {it['text']}" for it in lst]
    return "任务清单已设置：\n" + "\n".join(lines)


@tool('check_todo')
def _exec_check_todo(
    todo_id: Annotated[str, Field(description='要标记为完成的任务 id（即 set_todolist 里的 id）')],
) -> str:
    """把任务清单中的一项标记为完成（todo_id 取 set_todolist 中的 id）。全部完成后据此汇报结果。"""
    ctx = current_tool_ctx()
    sid = ctx.session_id or ""
    if not _check_todo(sid, (todo_id or "").strip()):
        return f"(未找到任务 {todo_id})"
    lst = _get_todolist(sid)
    done = sum(1 for it in lst if it["done"])
    if done >= len(lst):
        return f"(已完成 {done}/{len(lst)} —— 全部任务完成，可以汇报结果)"
    return f"(已完成 {done}/{len(lst)})"


@tool('read_workflow')
def _exec_read_workflow(
    name: Annotated[str, Field(description="工作流名称，如 Autoplan、DeepResearch 等")],
) -> str:
    """读取指定工作流（如 Autoplan、DeepResearch）的完整执行说明；开始一个专门/复杂任务前先调用以获取分步做法。"""
    ctx = current_tool_ctx()
    name = (name or "").strip()
    if not name:
        return "(未提供 name 参数)"
    router = getattr(ctx, "workflow_router", None)
    if not router:
        return "(工作流路由器未就绪)"
    content = router.get_workflow_content(name)
    if not content:
        return f"(未找到工作流: {name})"
    return f"工作流{name}\n\n{content}"
