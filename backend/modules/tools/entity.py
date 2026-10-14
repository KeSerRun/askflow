"""modules/tools.entity —— 工具定义的数据库记录（ORM 领域模型）。"""

from __future__ import annotations

from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy.orm import mapped_column

from infra.adapters.storage import Base


class AgentTool(Base):
    """一个 Agent 工具的完整定义（元数据 + handler 代码）。

    - ``parameters`` / ``code`` 存文本（JSON / Python 源码）；
    - 运行时由 ``ToolRegistry.load_defs`` 装载，``code`` 存在则以代码执行为准。
    """

    __tablename__ = "agent_tools"

    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    name = mapped_column(String(64), nullable=False, unique=True, index=True)
    description = mapped_column(Text, nullable=False)
    parameters = mapped_column(Text, nullable=False)          # JSON Schema 文本
    code = mapped_column(Text, nullable=False)                # handler 代码（定义 handle(args, ctx)）
    handler_module = mapped_column(String(128), nullable=True)  # 代码执行命名空间（内建种子用）
    enabled = mapped_column(Boolean, nullable=False, default=True)
    concurrent_safe = mapped_column(Boolean, nullable=False, default=False)
    sort_order = mapped_column(Integer, nullable=False, default=0)
    call_count = mapped_column(Integer, nullable=False, default=0)   # 累计调用次数（仪表盘统计）
    updated_at = mapped_column(String(40), nullable=False)
