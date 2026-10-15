"""modules/database/dto.py —— 数据管理入参。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class MdViewActionBody(BaseModel):
    """文档视图手动调整（嵌入 / 移除）请求体。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    source: str = Field(min_length=1)
    page: int = Field(ge=1)
    block_idx: int = Field(ge=0)
    partition: str | None = Field(default=None, description="知识库名；留空用 __system__")
