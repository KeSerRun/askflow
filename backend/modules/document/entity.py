"""modules/document/entity.py —— 文档领域实体。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class UploadResult:
    """上传结果。"""

    filename: str
    chunks: int = 0
    sources: list = field(default_factory=list)
