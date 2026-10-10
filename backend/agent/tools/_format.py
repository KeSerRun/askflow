"""检索结果格式化工具函数。

将向量检索返回的 Document 列表格式化为 LLM 易读的文本。
每个块附带元数据标头（来源、章节路径、页码、文档类型、分区标记），
如果是图片 / 图表块且关联了图片路径，则追加 Markdown 图片引用。

此模块由 _kb_handlers.py 调用，不直接对外暴露工具 handler。
"""

from pathlib import Path
from typing import List

from core.models import Document

SYSTEM_PARTITION = "__system__"


def _format_chunk(idx: int, chunk: Document) -> str:
    """格式化单个检索块为带元数据的文本。

    生成如下的标头行：
        【片段 1 | **来源** | 章节A > 章节B | p.10 | chart】[id=abc123]

    对于图片 / 图表块，如果 metadata 中包含 img_path，还会附加 Markdown 图片引用。

    Args:
        idx: 块序号（从 1 开始）。
        chunk: 检索结果 Document 对象，含 page_content（文本）和 metadata（元数据字典）。

    Returns:
        格式化的文本字符串，包含标头和正文。
    """
    meta = chunk.metadata or {}
    parts = []
    source = (meta.get("source") or "").strip()
    if source:
        parts.append(f"**{source}**")
    section_path = meta.get("section_path") or []
    if section_path:
        parts.append(" > ".join(s for s in section_path if s))
    page = meta.get("page")
    if page is not None:
        parts.append(f"p.{page}")
    chunk_type = (meta.get("chunk_type") or "").strip()
    if chunk_type and chunk_type != "text":
        parts.append(chunk_type)
    partition = (meta.get("partition") or "").strip()
    if partition == SYSTEM_PARTITION:
        parts.append("\U0001f4d6 系统文档")
    elif partition:
        parts.append("\U0001f4c4 用户文档")
    chunk_id = (meta.get("id") or "")[:8]
    id_tag = f" [id={chunk_id}]" if chunk_id else ""
    header = f"【片段 {idx} | {' | '.join(parts)}】{id_tag}" if parts else f"【片段 {idx}】{id_tag}"
    body = chunk.page_content.strip()
    img_path = (meta.get("img_path") or "").strip()
    if img_path and chunk_type in ("image", "chart") and source:
        stem = Path(source).stem
        img_md = f"\n\n![图](/api/documents/image/{stem}/{img_path})"
        return f"{header}\n{body}{img_md}"
    return f"{header}\n{body}"


def format_retrieved_chunks(chunks: List[Document]) -> str:
    """将一组检索块拼接为完整上下文文本。

    遍历 chunks 列表，为每个块调用 _format_chunk 生成带元数据标头的文本块，
    块之间以两个换行符分隔。空列表返回空字符串。
    在末尾附加 read_chunk_context 调用提示（从首个 chunk_id 生成示例调用）。

    Args:
        chunks: 检索结果 Document 列表。

    Returns:
        拼接后的文本字符串。空列表时返回空字符串。
    """
    if not chunks:
        return ""
    text = "\n\n".join(_format_chunk(i + 1, c) for i, c in enumerate(chunks))

    if chunks:
        ids = set()
        for c in chunks[:3]:
            cid = (c.metadata.get("id") or "")[:8]
            if cid:
                ids.add(cid)
        if ids:
            example_id = next(iter(ids))
            text += (
                "\n\n---\n"
                "\U0001f4a1 如需查看某个片段前后的更多上下文，可调用 "
                "read_chunk_context(chunk_id=\"" + example_id + "\", before=3, after=3)"
            )

    return text