"""adapters.pdf.mineru —— MinerU PDF 结构化解析（ports.PdfParser 实现）。

基于本目录的 mineru_impl（MinerU API 客户端 + 分块）：
字节流 → 临时文件 → MinerU API → 标准化 ParsedChunk。
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from .mineru_impl import MinerUPDFLoader, MinerUError, PdfParseError
from .models import ParsedChunk


class MineruParser:
    """基于 MinerU API 的 PDF 解析适配器。"""

    def __init__(self, work_dir: str):
        """初始化。

        Args:
            work_dir: 解析临时工作根目录（每次解析使用其下独立子目录，完成后清理）。
        """
        self._work_dir = Path(work_dir)
        self._work_dir.mkdir(parents=True, exist_ok=True)

    # ── PdfParser ──

    def parse(self, pdf_bytes: bytes, filename: str) -> list[ParsedChunk]:
        """解析 PDF 字节流为标准化分块。

        Args:
            pdf_bytes: PDF 内容。
            filename: 原文件名（仅用于元数据/报错）。

        Returns:
            ParsedChunk 列表。

        Raises:
            PdfParseError: 解析失败。
        """
        if not pdf_bytes:
            raise PdfParseError("PDF 内容为空")

        session_dir = tempfile.mkdtemp(prefix="mineru_", dir=self._work_dir)
        try:
            tmp_pdf = os.path.join(session_dir, _sanitize_name(filename))
            with open(tmp_pdf, "wb") as f:
                f.write(pdf_bytes)

            docs = MinerUPDFLoader(tmp_pdf).load()

            chunks: list[ParsedChunk] = []
            for d in docs:
                meta = d.metadata or {}
                chunks.append(ParsedChunk(
                    content=d.page_content,
                    chunk_type=meta.get("chunk_type") or "text",
                    page=meta.get("page") or 0,
                    metadata={
                        k: v for k, v in meta.items()
                        if k not in ("source", "pre_chunked")
                    },
                ))
            return chunks

        except MinerUError as e:
            raise PdfParseError(f"MinerU 解析失败: {e}") from e
        except Exception as e:
            raise PdfParseError(f"PDF 解析异常: {e}") from e
        finally:
            shutil.rmtree(session_dir, ignore_errors=True)


def _sanitize_name(filename: str) -> str:
    """净化文件名（防解析器/输出目录路径穿越）。"""
    base = Path(filename).name or "upload.pdf"
    if not base.lower().endswith(".pdf"):
        base += ".pdf"
    return base