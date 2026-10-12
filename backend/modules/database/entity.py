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