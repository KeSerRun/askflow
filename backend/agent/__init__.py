"""Agent 核心模块: LangGraph 状态机 + 工具注册 + 断点续跑。

该模块是 RAG 系统的 Agent 层，提供以下核心能力:
  - IntegratedSystem: 高层集成入口
  - ToolLoop: LangGraph 编排的 tool-calling 循环
  - ToolRegistry / ToolContext / ToolDef: 工具注册与执行引擎
  - CheckpointStore: 图运行快照（断点续跑）

子模块结构:
  - agent/state.py:     图状态（GraphState）
  - agent/loop.py:      ToolLoop 状态机
  - agent/context.py:   SkillLoader 风格 prompt 加载
  - agent/checkpoint.py: 断点快照持久化
  - agent/tools/:       工具注册、执行与 schemas
"""

from .checkpoint import CheckpointStore
from .context import SystemContext, WorkflowRouter
from .integrate import IntegratedSystem
from .loop import ToolLoop
from .tools import registry
from .tools.registry import ToolContext, ToolDef, ToolRegistry

__all__ = [
    "ToolLoop",
    "IntegratedSystem",
    "CheckpointStore",
    "ToolRegistry",
    "ToolContext",
    "ToolDef",
    "registry",
    "WorkflowRouter",
    "SystemContext",
]
