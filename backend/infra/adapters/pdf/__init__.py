"""adapters.pdf —— PDF 解析适配器。"""

from .mineru import MineruParser  # noqa: F401
from .models import ParsedChunk  # noqa: F401

__all__ = ["MineruParser", "ParsedChunk"]