"""modules/database.entity —— 数据管理相关数据库记录（ORM 领域模型）。"""

from __future__ import annotations

from sqlalchemy import String, Text
from sqlalchemy.orm import mapped_column

from infra.adapters.storage import Base


class ChunkParent(Base):
    """正文父块内容（按 parent_id 去重入库一次，避免向量库每行重复存父块全文）。

    - ``id``：``parent_id = md5(父块全文)``；
    - ``text``：父块（未切分的正文块）全文。
    子块在向量库只存 ``parent_id`` 引用，展示"父块"时按 id 回查本表。
    """

    __tablename__ = "chunk_parents"

    id = mapped_column(String(64), primary_key=True)
    text = mapped_column(Text, nullable=False)


class KnowledgeBase(Base):
    """知识库（向量库 partition 的元信息）。

    知识库在向量库中表现为 ``partition`` 字段值；本表持有其**目录信息**
    （名称 / 描述 / 创建时间），使空知识库（尚未上传文档）在管理端也能列出、
    可改名、可删除，而不必依赖向量库已有向量。

    - ``id``：``partition`` 值（知识库名称，主键，与向量库 partition 一一对应）；
    - ``description``：给 Agent 看的知识库用途描述（``list_knowledge_bases`` 工具会返回）；
    - ``created_at``/``updated_at``：ISO 时间字符串。
    """

    __tablename__ = "knowledge_bases"

    id = mapped_column(String(128), primary_key=True)
    description = mapped_column(Text, nullable=False, default="")
    created_at = mapped_column(String(40), nullable=False)
    updated_at = mapped_column(String(40), nullable=False)
