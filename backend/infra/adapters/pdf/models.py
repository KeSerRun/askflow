"""adapters.pdf.models —— PDF 解析产物类型（本适配器专属）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ParsedChunk:
    """PDF 解析器产出的一个标准化分块。

    Attributes:
        content: 块正文。
        chunk_type: text / table / chart / image。
        page: 页码（1 起）。
        metadata: 附加元数据（section_path/caption/img_path/table_body 等）。
    """

    content: str
    chunk_type: str = "text"
    page: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
