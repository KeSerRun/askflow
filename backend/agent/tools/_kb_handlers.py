"""agent.tools._kb_handlers —— 工具 handler 实现（@tool 声明 + langchain 类型签名推导；辅助函数在 _common）。"""
from __future__ import annotations
from typing import Annotated
from pydantic import Field
from ._common import (_cache_get, _cache_set, _cfg, _get_file_stats,
                      _list_session_docs, _hybrid_retrieve, _read_doc_text,
                      _resolve_image_bytes, format_retrieved_chunks)
from ._context import current_tool_ctx, tool
from infra.util.logger import logger
from pathlib import Path



@tool('search_knowledge_base', concurrent_safe=True)
def _exec_search_kb(
    queries: Annotated[list[str] | None,
                       Field(description="文本检索查询，最多 5 个；可空（仅图片检索时省略）")] = None,
    images: Annotated[list[str] | None,
                      Field(description="图片引用（MinIO 对象键或 /api/documents/image/... 直链），最多 5 个；"
                                         "可空（仅文本检索时省略）")] = None,
    top_k: Annotated[int | None, Field(description="返回结果数，默认 10，留空用默认")] = 10,
    mode: Annotated[str, Field(description="检索输出作用域：mixed（混合，默认）/ text（只返回文本块）/ image（只返回图片块）")] = "mixed",
) -> str:
    """多模态混合检索知识库：接收文本列表与图片引用列表，各自向量化后做混合检索并按 RRF 重排，返回相关文本片段与图片直链。"""
    ctx = current_tool_ctx()
    mode = (mode or "mixed").strip().lower()
    if mode not in ("mixed", "text", "image"):
        mode = "mixed"
    texts = [str(q).strip() for q in (queries or []) if str(q).strip()]
    image_refs = [str(i).strip() for i in (images or []) if str(i).strip()]
    if not texts and not image_refs:
        return "(未提供有效查询：queries（文本）与 images（图片引用）至少给其一)"

    top_k = int(top_k or 10)
    top_k = max(1, min(top_k, _cfg(ctx, "retrieval_top_k", 50)))
    logger.debug(f"tool search_knowledge_base mode={mode} texts={len(texts)} images={len(image_refs)}")

    chunks = _hybrid_retrieve(
        ctx, texts, image_refs,
        retrieval_top_k=_cfg(ctx, "retrieval_top_k", 50),
        chunk_filter=mode,
    )
    if not chunks:
        return "(知识库中未检索到相关内容)"

    chunks = chunks[:top_k]

    img_lines = []
    for c in chunks:
        meta = c.metadata or {}
        ip, src = (meta.get("img_path") or "").strip(), (meta.get("source") or "").strip()
        if ip and src:
            img_lines.append(f"- ![图](/api/documents/image/{Path(src).stem}/{ip})　来源：{src}")

    formatted = format_retrieved_chunks(chunks)

    mode_label = {"mixed": "多模态混合", "text": "文本块", "image": "图片块"}[mode]
    n_text = sum(1 for c in chunks
                 if str((c.metadata or {}).get("chunk_type", "")).strip() == "text")
    n_img = sum(1 for c in chunks
                if str((c.metadata or {}).get("chunk_type", "")).strip() in ("image", "chart"))
    parts = [f"{mode_label}检索命中 {len(chunks)} 块（文本块 {n_text} + 图片块 {n_img}）"]
    if img_lines:
        parts.append("命中图片：\n" + "\n".join(img_lines))
    parts.append(formatted)
    return "\n\n".join(parts)


@tool('ocr_image', concurrent_safe=True)
def _exec_ocr_image(
    image: Annotated[str, Field(description="图片引用：MinIO 对象键或 /api/documents/image/... 直链")],
) -> str:
    """对单张图片做 OCR（本地 MinerU），识别截图/图表/扫描件里的中英文文字，返回文本内容。"""
    ctx = current_tool_ctx()
    image = (image or "").strip(' "`')
    if not image:
        return "(未提供 image 参数)"
    data = _resolve_image_bytes(ctx, image)
    if data is None:
        return f"(无法解析图片引用：{image[:60]})"
    try:
        from infra.adapters.pdf.mineru_impl import ocr_image_bytes

        text = ocr_image_bytes(data, Path(image).name or "image.png")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"tool ocr_image 失败: {e}")
        return f"(OCR 失败：{e})"
    if not text:
        return "(未在图片中识别出文字)"
    return f"[OCR 识别结果]\n{text}"


@tool('read_full_document')
def _exec_read_full_document(
    filename: Annotated[str, Field(description="文档名（不含扩展名）")],
    offset: Annotated[int, Field(description="字符偏移，用于分页续读")] = 0,
    max_chars: Annotated[int | None, Field(description="本次最多读取字符数")] = None,
) -> str:
    """读取指定文档的完整全文（知识库文档或当前会话已解析的上传附件），支持 offset 分页续读。"""
    ctx = current_tool_ctx()
    filename = (filename or "").strip()
    if not filename:
        return "(未提供 filename 参数)"

    content = _read_doc_text(ctx, filename)
    if content is None:
        logger.warning(f"tool read_full_document 未找到: {filename}")
        return f"(未找到 {filename} 的全文，可能该文档不是由 MinerU 解析的)"

    try:
        cache_key = f"full_text:{filename}"
        cached = _cache_get(ctx, cache_key)
        if cached is not None:
            content = cached
        else:
            _cache_set(ctx, cache_key, content)
        total = len(content)
        max_chars = max_chars or _cfg(ctx, "context_tool_page_chars", 5000)
        offset = max(int(offset), 0)
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


@tool('list_documents', concurrent_safe=True)
def _exec_list_documents(
    pattern: Annotated[str | None, Field(description="文件名关键词过滤")] = None,
    sort_by: Annotated[str, Field(description="排序方式：'name' 或 'time'")] = 'name',
) -> str:
    """列出知识库与当前会话的可用文档，支持关键词过滤与按名称/时间排序，会话附件带标记。"""
    ctx = current_tool_ctx()
    if not ctx.vector_store:
        return "(知识库不可用)"
    pattern = (pattern or "").strip().lower()
    sort_by = sort_by
    logger.debug(f"tool list_documents pattern={pattern!r} sort={sort_by}")

    system_docs = ctx.vector_store.get_documents() or []
    doc_entries = []
    for d in system_docs:
        s = _get_file_stats(d, object_store=getattr(ctx, "object_store", None))
        doc_entries.append({"name": d, **s, "is_system": True})

    # 当前会话已解析的上传附件（对话页上传 → MinerU 解析为 txt，不进向量库）
    session_docs = _list_session_docs(ctx)
    seen = {d["name"] for d in doc_entries}
    for d in session_docs:
        if d not in seen:
            doc_entries.append({"name": d, "size": "", "mtime": "", "type": "会话附件", "is_system": False})
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


@tool('read_chunk_context', concurrent_safe=True)
def _exec_read_chunk_context(
    chunk_id: Annotated[str, Field(description="目标 chunk ID")],
    before: Annotated[int, Field(description="向前取块数，上限 10")] = 3,
    after: Annotated[int, Field(description="向后取块数，上限 10")] = 3,
) -> str:
    """按 chunk ID 读取目标块及其前后相邻块以补全上下文（目标块以【目标】标记）。"""
    ctx = current_tool_ctx()
    chunk_id = (chunk_id or "").strip()
    before = before
    after = after
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
        ctype = str(m.get("chunk_type") or "").strip()
        text = m.get("text", "")
        if not text and ctype in ("image", "chart"):
            # 图片块 text 为空：显示 [图:img_path] + caption，与 txt 渲染口径一致
            ip = (m.get("img_path") or "").strip()
            cap = (m.get("caption") or "").strip()
            text = f"[图:{ip}] {cap}" if ip else (f"[图] {cap}" if cap else "[图]")
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


@tool('search_document_content')
def _exec_search_document_content(
    keyword: Annotated[str, Field(description="搜索关键词，大小写不敏感")],
    source: Annotated[str | None, Field(description="限定单篇文档名（不含扩展名）")] = None,
    max_results: Annotated[int, Field(description="最大匹配数，上限 50")] = 10,
) -> str:
    """在知识库与会话附件的全文（txt 渲染）中按关键词搜索，返回命中的文档名与上下文片段。"""
    ctx = current_tool_ctx()
    keyword = (keyword or "").strip()
    if not keyword:
        return "(未提供 keyword 参数)"
    source_filter = (source or "").strip().lower()
    max_results = min(int(max_results), 50)

    logger.debug(f"tool search_document_content keyword={keyword!r} source={source_filter!r}")

    if not ctx.vector_store:
        return "(知识库不可用)"

    try:
        system_docs = ctx.vector_store.get_documents() or []
    except Exception:
        system_docs = []

    if source_filter == "__system__":
        doc_names = system_docs
    elif source_filter:
        doc_names = [source_filter]
    else:
        # 系统文档 + 当前会话已解析的上传附件（不进向量库）
        doc_names = list(dict.fromkeys(system_docs + _list_session_docs(ctx)))

    keyword_lower = keyword.lower()
    matches = []

    for doc in doc_names:
        content = _read_doc_text(ctx, doc)
        if content is None:
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
