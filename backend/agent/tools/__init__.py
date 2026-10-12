"""Agent 工具注册表入口。

- handler 按功能拆分在 ``_kb_handlers.py`` / ``_web_handlers.py`` / ``_infra_handlers.py``，
  每个工具直接用 langchain ``@tool`` 声明；
- ``BUILTIN_TOOLS``（由 ``collect_tools`` 扫描生成）**仅用于启动时把内建工具种子写入数据库**；
- 运行时工具一律从数据库（``agent_tools``）经 ``registry.load_defs`` 加载，无兜底注册。
"""

from ._common import SYSTEM_PARTITION, format_retrieved_chunks
# 导入三个 handler 模块（其内部已用 langchain @tool 直接装饰 _exec_*，成为 BaseTool）
from . import _infra_handlers  # noqa: F401
from . import _kb_handlers  # noqa: F401
from . import _web_handlers  # noqa: F401
from .registry import ToolRegistry, collect_tools

# 填充 BUILTIN_TOOLS（种子数据源；运行时装载由数据库驱动）
collect_tools(_kb_handlers, _web_handlers, _infra_handlers)

# 运行时注册表：组合根装配时按数据库调用 load_defs 填充
registry = ToolRegistry()

__all__ = ["registry", "SYSTEM_PARTITION", "format_retrieved_chunks"]