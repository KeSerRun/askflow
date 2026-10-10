"""KB 工具 handlers：知识库检索 / 读全文 / 列文档。

提供知识库相关的工具 handler 实现：
  - search_knowledge_base: 多 query + 多分区 + 去重检索
  - read_full_document: 读取文档全文（MinerU 解析后的 Markdown）
  - list_documents: 列出用户 / 系统分区文档
  - read_chunk_context: 读取某 chunk 前后的上下文
  - read_document_titles: 读取文档 Markdown 标题结构
  - read_section: 根据标题关键词定位并读取正文
  - search_document_content: 全文关键词搜索

注册统一在 registry.py 的 register_all_builtins() 中完成。
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from infra.logger import logger
from core.models import Document

from .registry import ToolContext
from ._format import SYSTEM_PARTITION, format_retrieved_chunks
from .cache import get as cache_get, set as cache_set
from ._common import _cfg, _data_dir


# ── RRF 重排 ──────────────────────────────────────────────────────


_RRF_K_DEFAULT = 60

def rrf_rerank(
    ranked_results: list[tuple[int, int, Document]],
    k: int = _RRF_K_DEFAULT,
    top_n: int | None = None,
) -> List[Document]:
    """Reciprocal Rank Fusion 重排。

    将多个 query 的检索结果按 RRF 算法融合：同一 chunk 在多个 query 中排名越高，
    融合分数越高。公式 score = Σ 1/(k + rank_i)。单 query 时等效于原始排序。

    Args:
        ranked_results: 带排名的结果列表，每个元素为 (query_index, rank_1based, Document)。
        k: RRF 平滑常数，默认 60。
        top_n: 返回前 N 条，None 返回全部。

    Returns:
        按 RRF 分数降序排列的 Document 列表。
    """
    if not ranked_results:
        return []

    scores: dict[str, tuple[Document, float]] = {}
    for qi, rank, doc in ranked_results:
        key = doc.metadata.get("id") or doc.page_content
        if key not in scores:
            scores[key] = (doc, 0.0)
        old_doc, old_score = scores[key]
        scores[key] = (old_doc, old_score + 1.0 / (k + rank))

    sorted_items = sorted(scores.values(), key=lambda x: -x[1])
    merged = [doc for doc, _ in sorted_items]

    if top_n is not None:
        merged = merged[:top_n]

    return merged


def _resolve_full_md(filename: str, partition: str | None = None, *,
                     data_dir: str) -> str | None:
    """解析文档 full.md 路径，供多个工具共享。

    在用户分区和系统分区下同时搜索 full.md，含路径穿越防护。

    Args:
        filename: 文档文件名（含扩展名）。
        partition: 用户分区名。
        data_dir: 数据根目录（必填，由调用方注入）。

    Returns:
        full.md 的绝对路径字符串，未找到时返回 None。
    """
    stem = Path(filename).stem
    base = Path(data_dir) / "uploads"
    candidates = [base / (partition or "") / "chunk_out" / stem / "full.md"]
    if partition and partition != "__system__":
        candidates.append(base / "__system__" / "chunk_out" / stem / "full.md")
    for full_md in candidates:
        try:
            r = full_md.resolve()
            r.relative_to(base.resolve())
            if r.is_file():
                return str(r)
        except (ValueError, OSError):
            continue
    return None


# ── 知识库检索 ──


def _exec_search_kb(args: dict, ctx: ToolContext) -> str:
    """工具 handler：search_knowledge_base。

    多 query + 多分区 + 全局去重检索知识库。
    单 query 走快速路径，多 query 公平分配 top_k。
    自动附加 read_chunk_context 调用提示。

    Args:
        args: 工具参数字典，键:
            queries: 检索查询列表（必填，1-5 个）。
            search_system: 是否同时搜索系统文档（可选，默认 True）。
            top_k: 返回结果数（可选，默认 5）。
        ctx: 工具运行时上下文。

    Returns:
        format_retrieved_chunks 格式化后的文本，含上下文提示。
    """
    queries = args.get("queries") or []
    if isinstance(queries, str):
        queries = [queries]
    queries = [str(q).strip() for q in queries if str(q).strip()]
    if not queries:
        logger.warning("tool search_knowledge_base 被调用但未提供有效 query")
        return "(未提供任何检索 query)"

    search_system = args.get("search_system", True)
    top_k = int(args.get("top_k", _cfg(ctx, "retrieval_candidate_k", 10)))
    top_k = max(1, min(top_k, _cfg(ctx, "retrieval_top_k", 50)))
    system_partitions = [SYSTEM_PARTITION] if search_system else None
    logger.debug(f"tool search_knowledge_base queries={queries} partition={ctx.partition} search_system={search_system} top_k={top_k}")

    chunks = _retrieve_and_dedup(ctx.vector_store, queries, ctx.partition, system_partitions,
                                 retrieval_top_k=_cfg(ctx, "retrieval_top_k", 50))
    if not chunks:
        logger.debug("tool search_knowledge_base 未检索到相关内容, 返回 0 块")
        return "(知识库中未检索到相关内容)"

    chunks = chunks[:top_k]

    for ci, c in enumerate(chunks):
        meta = c.metadata or {}
        logger.debug(
            f"检索块 {ci+1}/{len(chunks)}] source={meta.get('source','')!r} "
            f"type={meta.get('chunk_type','')!r} section={meta.get('section_path',[])} "
            f"page={meta.get('page')} caption={meta.get('caption','')!r} "
            f"img={meta.get('img_path','')!r} len={len(c.page_content)}"
        )
        preview = c.page_content[:200].replace("\n", " ")
        logger.debug(f"检索块 {ci+1} 内容] {preview}")

    formatted = format_retrieved_chunks(chunks)
    logger.debug(f"tool search_knowledge_base 命中 {len(chunks)} 块, 上下文长度={len(formatted)}")
    return formatted


# ── 文档全文读取 ──


def _exec_read_full_document(args: dict, ctx: ToolContext) -> str:
    """工具 handler：read_full_document。

    读取 MinerU 解析后的完整文档全文（Markdown 格式）。
    支持 offset 分页，分页大小由配置 conf.context_tool_page_chars 决定。

    Args:
        args: 工具参数字典，键:
            filename: 文档文件名（含扩展名，必填）。
            offset: 字符偏移位置（可选，默认 0）。
        ctx: 工具运行时上下文。

    Returns:
        文档全文片段，末尾附带分页提示。
    """
    filename = (args.get("filename") or "").strip()
    if not filename:
        return "(未提供 filename 参数)"

    resolved = _resolve_full_md(filename, ctx.partition, data_dir=_data_dir(ctx))
    if resolved is None:
        logger.warning(f"tool read_full_document 未找到: {filename}")
        return f"(未找到 {filename} 的全文，可能该文档不是由 MinerU 解析的)"

    try:
        cache_key = f"full_md:{filename}"
        content = cache_get(cache_key)
        if content is None:
            content = Path(resolved).read_text(encoding="utf-8")
            cache_set(cache_key, content)
        total = len(content)
        max_chars = args.get("max_chars") or _cfg(ctx, "context_tool_page_chars", 5000)
        offset = max(int(args.get("offset", 0)), 0)
        chunk = content[offset:offset + max_chars]
        part_info = ""
        if total > max_chars:
            end = offset + len(chunk)
            if end < total:
                part_info = f"\n\n(第 {offset}-{end} 字符，共 {total} 字符。调用 offset={end} 继续阅读)"
            else:
                part_info = f"\n\n(第 {offset}-{end} 字符，共 {total} 字符 — 已到末尾)"
        logger.debug(f"tool read_full_document 成功: {filename} (返回 {len(chunk)}/{total} 字符)")
        return chunk + part_info
    except Exception as e:
        logger.warning(f"tool read_full_document 读取失败 ({filename}): {e}")
        return f"(读取 {filename} 失败: {e})"


def _get_file_stats(filename: str, partition: str | None = None, *,
                    data_dir: str) -> dict:
    """获取文档文件的元信息（大小、修改时间、类型）。

    Args:
        filename: 文档文件名。
        partition: 分区名。

    Returns:
        包含 'size'、'mtime'、'type' 三个键的字典，各字段可能为空字符串。
    """
    import datetime as _dt

    stats = {"size": "", "mtime": "", "type": ""}
    resolved = _resolve_full_md(filename, partition, data_dir=data_dir)
    if resolved:
        try:
            s = Path(resolved).stat()
            size = s.st_size
            if size < 1024:
                stats["size"] = f"{size}B"
            elif size < 1024 * 1024:
                stats["size"] = f"{size / 1024:.0f}KB"
            else:
                stats["size"] = f"{size / 1024 / 1024:.1f}MB"
            mtime = _dt.datetime.fromtimestamp(s.st_mtime).strftime("%m-%d %H:%M")
            stats["mtime"] = mtime
        except OSError:
            pass
    ext = Path(filename).suffix.lower()
    if ext == ".pdf":
        stats["type"] = "PDF"
    elif ext in (".docx", ".doc"):
        stats["type"] = "Word"
    elif ext in (".xlsx", ".xls"):
        stats["type"] = "Excel"
    elif ext in (".pptx", ".ppt"):
        stats["type"] = "PPT"
    elif ext in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"):
        stats["type"] = "Image"
    elif ext in (".md", ".markdown"):
        stats["type"] = "Markdown"
    elif ext in (".txt",):
        stats["type"] = "Text"
    elif ext:
        stats["type"] = ext[1:].upper()
    return stats


# ── 文档清单 ──


def _exec_list_documents(args: dict, ctx: ToolContext) -> str:
    """工具 handler：list_documents。

    列出用户 / 系统分区的文档，支持关键词过滤和排序。
    返回文档名、类型、大小、修改时间。

    Args:
        args: 工具参数字典，键:
            pattern: 文件名关键词过滤（可选）。
            list_system: 是否同时列出系统文档（可选，默认 True）。
            sort_by: 排序方式，'name' 或 'time'（可选，默认 'name'）。
        ctx: 工具运行时上下文。

    Returns:
        格式化的文档列表文本。
    """
    if not ctx.vector_store:
        return "(知识库不可用)"
    pattern = (args.get("pattern") or "").strip().lower()
    list_system = args.get("list_system", True)
    sort_by = args.get("sort_by", "name")
    logger.debug(f"tool list_documents pattern={pattern!r} list_system={list_system} "
                 f"partition={ctx.partition} sort={sort_by}")

    user_docs = ctx.vector_store.get_documents_by_partition(partition=ctx.partition) or []
    doc_entries = []
    for d in user_docs:
        s = _get_file_stats(d, ctx.partition, data_dir=_data_dir(ctx))
        doc_entries.append({"name": d, **s, "is_system": False})

    if list_system:
        system_docs = ctx.vector_store.get_documents_by_partition(partition=SYSTEM_PARTITION) or []
        seen = {d["name"] for d in doc_entries}
        for d in system_docs:
            if d not in seen:
                s = _get_file_stats(d, SYSTEM_PARTITION, data_dir=_data_dir(ctx))
                doc_entries.append({"name": d, **s, "is_system": True})
                seen.add(d)

    if pattern:
        doc_entries = [d for d in doc_entries if pattern in d["name"].lower()]

    if not doc_entries:
        return "(当前没有匹配的文档)"

    if sort_by == "time":
        doc_entries.sort(key=lambda d: (not bool(d["mtime"]), d["mtime"]), reverse=True)
    else:
        doc_entries.sort(key=lambda d: d["name"].lower())

    lines = []
    for d in doc_entries:
        icon = "📖" if d["is_system"] else "📄"
        info = " | ".join(p for p in [d["type"], d["size"], d["mtime"]] if p)
        if info:
            lines.append(f"- {icon} {d['name']}  ({info})")
        else:
            lines.append(f"- {icon} {d['name']}")

    return "当前知识库中的文档：\n" + "\n".join(lines)


# ── 多 query 多分区检索 ──


def _retrieve_and_dedup(
    vector_store, queries, partition, system_partitions: Optional[list] = None,
    retrieval_top_k: Optional[int] = None,
) -> List[Document]:
    """多 query + 多分区 + RRF 重排检索。

    对每个 query 在各分区中检索，使用 rrf_rerank 融合多个 query 的结果。
    单 query 时 RRF 等效于原始排序。

    Args:
        vector_store: 向量存储实例。
        queries: 检索查询字符串列表。
        partition: 用户分区名。
        system_partitions: 要搜索的系统分区名列表（可选）。

    Returns:
        按 RRF 分数降序排列的 Document 列表。
    """
    if not queries:
        return []

    search_partitions = [partition] if partition else []
    if system_partitions:
        search_partitions.extend(sp for sp in system_partitions if sp and sp not in search_partitions)

    # 收集每个分区中每个 query 的原始结果（含排名）
    all_ranked: list[tuple[int, int, Document]] = []
    for p in search_partitions:
        for qi, q in enumerate(queries):
            try:
                results = vector_store.search(query=q, top_k=retrieval_top_k, partition=p)
            except Exception as e:
                logger.error(f"检索失败 (query={q!r}, partition={p}): {e}")
                continue
            for rank, doc in enumerate(results, 1):
                all_ranked.append((qi, rank, doc))

    if not all_ranked:
        logger.debug("多分区检索未检索到相关内容, 返回 0 块")
        return []

    merged = rrf_rerank(all_ranked)

    logger.debug(f"多分区检索完成: partitions={search_partitions}, RRF 重排后 {len(merged)} 块")
    return merged


# ── Chunk 上下文读取 ──


def _exec_read_chunk_context(args: dict, ctx: ToolContext) -> str:
    """工具 handler：read_chunk_context。

    根据 chunk ID 读取其前后相邻的文档块（按页面顺序），提供上下文。
    当 search_knowledge_base 返回的某个片段需要更多上下文时使用此工具，
    避免多次调用 search_knowledge_base。

    Args:
        args: 工具参数字典，键:
            chunk_id: 目标 chunk ID（必填）。
            before: 向前取多少块（可选，默认 3，最大 10）。
            after: 向后取多少块（可选，默认 3，最大 10）。
        ctx: 工具运行时上下文。

    Returns:
        相邻 chunks 的汇总文本，目标 chunk 标记为 【目标】。
    """
    chunk_id = (args.get("chunk_id") or "").strip()
    before = args.get("before", 3)
    after = args.get("after", 3)
    before = min(max(int(before), 0), 10)
    after = min(max(int(after), 0), 10)

    if not chunk_id:
        return "(未提供 chunk_id 参数)"

    if not ctx.vector_store:
        return "(知识库不可用)"

    meta_list = getattr(ctx.vector_store, "metadata", None)
    if not meta_list:
        return "(元数据不可用)"

    target_meta = None
    for m in meta_list:
        if str(m.get("id", "")).startswith(chunk_id):
            target_meta = m
            break
    if target_meta is None:
        return f"(未找到 chunk_id={chunk_id})"

    source = target_meta.get("source", "")
    partition = target_meta.get("partition", "")
    siblings = [
        m for m in meta_list
        if m.get("source") == source and m.get("partition") == partition
    ]
    siblings.sort(key=lambda m: (m.get("page") or 0))

    target_idx = None
    for i, m in enumerate(siblings):
        if str(m.get("id", "")).startswith(chunk_id):
            target_idx = i
            break
    if target_idx is None:
        return f"(chunk_id={chunk_id} 定位失败)"

    start = max(0, target_idx - before)
    end = min(len(siblings), target_idx + after + 1)
    selected = siblings[start:end]

    lines = []
    for m in selected:
        tag = "【目标】" if str(m.get("id", "")).startswith(chunk_id) else ""
        page_info = f" [第{m['page']}页]" if m.get("page") else ""
        lines.append(f"--- {tag}源:{m['source']}{page_info} ---")
        text = m.get("text", "")
        if len(text) > 500:
            text = text[:500] + "...(已截断)"
        lines.append(text)
        lines.append("")

    if not lines:
        return "(未获取到上下文)"

    output = "\n".join(lines)
    logger.debug(
        f"tool read_chunk_context 成功: "
        f"id={chunk_id[:12]} source={source} "
        f"range={start}-{end-1}/{len(siblings)} "
        f"({len(selected)}块)"
    )
    return output


# ── 文档标题目录 ──


def _exec_read_document_titles(args: dict, ctx: ToolContext) -> str:
    """工具 handler：read_document_titles。

    读取某篇文档的完整 Markdown 源文件，提取所有 Markdown 标题（# 开头）。
    返回文档的标题目录结构。配合 read_section 使用。

    Args:
        args: 工具参数字典，键:
            source: 文档文件名（含扩展名，必填）。
        ctx: 工具运行时上下文。

    Returns:
        格式化的标题层级文本。
    """
    source = (args.get("source") or "").strip()
    if not source:
        return "(未提供 source 参数)"

    resolved = _resolve_full_md(source, ctx.partition, data_dir=_data_dir(ctx))
    if resolved is None:
        return f"(未找到 {source} 的全文，可能该文档不是由 MinerU 解析的)"

    try:
        content = Path(resolved).read_text(encoding="utf-8")
    except Exception as e:
        return f"(读取 {source} 失败: {e})"

    lines = content.splitlines()
    headings = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#"):
            level = len(stripped) - len(stripped.lstrip("#"))
            text = stripped[level:].strip()
            if text:
                headings.append((level, text))

    if not headings:
        return f"(文档 {source} 中未找到 Markdown 标题)"

    output_lines = [f"📖 {source} 的文档结构："]
    for level, text in headings:
        indent = "  " * (level - 1)
        output_lines.append(f"{indent}- {text}")

    output = "\n".join(output_lines)
    logger.debug(f"tool read_document_titles 成功: {source} ({len(headings)} 个标题)")
    return output


# ── 文档章节定位读取 ──


def _exec_read_section(args: dict, ctx: ToolContext) -> str:
    """工具 handler：read_section。

    根据文档名和标题关键词，从 Markdown 源文件中定位该标题下的正文内容。
    与 read_document_titles 使用同一数据源，匹配更准确。
    支持精确匹配和关键词拆词匹配。

    Args:
        args: 工具参数字典，键:
            source: 文档文件名（含扩展名，必填）。
            heading: 标题关键词，匹配任意级别标题（必填）。
        ctx: 工具运行时上下文。

    Returns:
        该标题下的正文内容（最多 30000 字符），超出部分截断。
    """
    source = (args.get("source") or "").strip()
    heading = (args.get("heading") or "").strip()
    if not source:
        return "(未提供 source 参数)"
    if not heading:
        return "(未提供 heading 参数)"

    resolved = _resolve_full_md(source, ctx.partition, data_dir=_data_dir(ctx))
    if resolved is None:
        return f"(未找到 {source} 的全文，可能该文档不是由 MinerU 解析的)"

    try:
        content = Path(resolved).read_text(encoding="utf-8")
    except Exception as e:
        return f"(读取 {source} 失败: {e})"

    lines = content.splitlines()
    heading_positions = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("#"):
            level = 0
            for ch in stripped:
                if ch == "#":
                    level += 1
                else:
                    break
            text = stripped[level:].strip()
            if text:
                heading_positions.append((i, level, text))

    if not heading_positions:
        return f"(文档 {source} 中未找到 Markdown 标题)"

    heading_lower = heading.lower()
    best_match = None
    best_score = 0
    for idx, (_, level, text) in enumerate(heading_positions):
        text_lower = text.lower()
        if heading_lower in text_lower:
            score = len(heading) / len(text) if text else 0
            if score > best_score:
                best_score = score
                best_match = idx

    if best_match is None:
        for idx, (_, level, text) in enumerate(heading_positions):
            text_lower = text.lower()
            for kw in heading_lower.split():
                if len(kw) > 1 and kw in text_lower:
                    if best_match is None:
                        best_match = idx
                    break

    if best_match is None:
        return f"(未找到匹配标题「{heading}」的内容)"

    match_line, match_level, match_text = heading_positions[best_match]
    next_start = None
    for j in range(best_match + 1, len(heading_positions)):
        if heading_positions[j][1] <= match_level:
            next_start = heading_positions[j][0]
            break

    section_lines = lines[match_line:next_start]
    while section_lines and not section_lines[0].strip():
        section_lines = section_lines[1:]
    while section_lines and not section_lines[-1].strip():
        section_lines = section_lines[:-1]

    section_text = "\n".join(section_lines)

    if len(section_text) > 30000:
        section_text = section_text[:30000] + "\n\n...(已截断)"

    logger.debug(
        f"tool read_section 成功: {source} / {match_text} "
        f"({len(section_lines)} 行, {len(section_text)} 字符)"
    )
    return section_text


# ── 文档全文关键词搜索 ──


def _exec_search_document_content(args: dict, ctx: ToolContext) -> str:
    """工具 handler：search_document_content。

    在所有知识库文档的全文（full.md）中搜索关键词，返回匹配的文档名和上下文片段。
    类似 grep，但针对知识库文档。

    Args:
        args: 工具参数字典，键:
            keyword: 搜索关键词，大小写不敏感（必填）。
            source: 限定仅搜索某篇文档（可选）。
            max_results: 最大返回匹配数（可选，默认 10，上限 50）。
        ctx: 工具运行时上下文。

    Returns:
        格式化的搜索结果列表。
    """
    keyword = (args.get("keyword") or "").strip()
    if not keyword:
        return "(未提供 keyword 参数)"
    source_filter = (args.get("source") or "").strip().lower()
    max_results = min(int(args.get("max_results", 10)), 50)

    logger.debug(f"tool search_document_content keyword={keyword!r} source={source_filter!r}")

    if not ctx.vector_store:
        return "(知识库不可用)"

    try:
        system_docs = ctx.vector_store.get_documents_by_partition(partition=SYSTEM_PARTITION) or []
    except Exception:
        system_docs = []

    if source_filter == "__system__":
        doc_names = system_docs
    elif source_filter:
        doc_names = [source_filter]
    else:
        user_docs = ctx.vector_store.get_documents_by_partition(partition=ctx.partition) or []
        doc_names = list(dict.fromkeys(user_docs + system_docs))

    keyword_lower = keyword.lower()
    matches = []

    for doc in doc_names:
        resolved = _resolve_full_md(doc, ctx.partition, data_dir=_data_dir(ctx))
        if not resolved:
            resolved = _resolve_full_md(doc, SYSTEM_PARTITION, data_dir=_data_dir(ctx)) if ctx.partition else _resolve_full_md(doc, None, data_dir=_data_dir(ctx))
        if not resolved:
            continue

        try:
            content = Path(resolved).read_text(encoding="utf-8")
        except Exception:
            continue

        lines = content.splitlines()
        doc_matches = []
        for i, line in enumerate(lines, 1):
            if keyword_lower in line.lower():
                snippet = line.strip()[:200]
                doc_matches.append((i, snippet))

        if doc_matches:
            matches.append((doc, doc_matches))

        if sum(len(m[1]) for m in matches) >= max_results:
            break

    if not matches:
        return f"(未找到包含「{keyword}」的文档)"

    total = 0
    output_lines = [f"搜索「{keyword}」结果："]
    for doc, doc_matches in matches:
        output_lines.append(f"\n📄 {doc}（{len(doc_matches)} 处匹配）")
        for line_no, snippet in doc_matches:
            if total >= max_results:
                break
            output_lines.append(f"  L{line_no}: {snippet}")
            total += 1
        if total >= max_results:
            if len(matches) > 1 or len(matches[0][1]) > max_results:
                output_lines.append(f"\n...(仅显示前 {max_results} 个匹配)")
            break

    return "\n".join(output_lines)