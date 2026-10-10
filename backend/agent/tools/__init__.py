"""Agent 工具注册表入口。

handler 实现按职责拆分:
  - _kb_handlers.py    : 知识库检索 / 读全文 / 列文档 / 读归档
  - _web_handlers.py   : 联网搜索 / 读网页全文
  - _infra_handlers.py : 目标 / 状态 / 工作流等基础设施工具

工具统一通过 registry.register() 注册，由 register_all_builtins() 在导入时完成。
"""

from ._format import SYSTEM_PARTITION, format_retrieved_chunks
from .registry import ToolRegistry, register_all_builtins

registry = ToolRegistry()
register_all_builtins(registry)

__all__ = ["registry", "SYSTEM_PARTITION", "format_retrieved_chunks"]
