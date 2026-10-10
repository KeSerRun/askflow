"""modules/document/dto.py —— 文档入参。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class AddDocumentsBody(BaseModel):
    """添加本地目录文档。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    documents_path: str = Field(min_length=1)


class SourcesBody(BaseModel):
    """仅含 sources 列表的请求体。"""

    sources: list[str] = Field(min_length=1)