"""agent.tools._kb_handlers —— 工具 handler 实现（@tool 声明 + langchain 类型签名推导；辅助函数在 _common）。"""
from __future__ import annotations

from pathlib import Path
from typing import Annotated

from pydantic import Field

from infra.util.logger import logger

from ._common import (
    _IMAGE_EXTS,
    _cache_get,
    _cache_set,
    _cfg,
    _get_file_stats,
    _hybrid_retrieve,
    _list_session_docs,
    _list_session_resources,
    _read_doc_text,
    _read_session_text,
    _read_system_text,
    _resolve_image_bytes,
    format_retrieved_chunks,
    replace_img_placeholders,
)
from ._context import current_tool_ctx, tool


@tool('list_knowledge_bases', concurrent_safe=True)
def _exec_list_knowledge_bases() -> str:
    """列出所有可用的知识库及其描述、文档数与切块数。

    检索前先调用本工具了解有哪些知识库、各自收录什么内容，再据此选择目标知识库
    调用 search_knowledge_base(partition=知识库名)。
    """
    ctx = current_tool_ctx()
    repo = getattr(ctx, "data_store", None)
    vs = getattr(ctx, "vector_store", None)
    vector_ok = vs is not None and getattr(vs, "is_available", lambda: True)()

    # 1) 目录（knowledge_bases 表）：含描述，空库也可见
    entries: dict[str, dict] = {}
    if repo is not None:
        try:
            for row in repo.find("knowledge_bases", order_by="id") or []:
                name = str(getattr(row, "id", "") or "").strip()
                if name:
                    entries[name] = {
                        "description": str(getattr(row, "description", "") or "").strip(),
                        "documents": 0, "chunks": 0,
                    }
        except Exception as e:  # noqa: BLE001
            logger.debug(f"读取知识库目录失败: {e}")

    # 2) 向量库统计：补齐遗留分区，并填文档/切块数
    if vector_ok:
        try:
            metadata = vs.metadata or []
            for m in metadata:
                part = str(m.get("partition") or "").strip()
                if not part:
                    continue
                e = entries.setdefault(part, {"description": "", "documents": 0, "chunks": 0})
                e["chunks"] += 1
                src = m.get("source")
                if src and src not in e.get("_sources", set()):
                    e.setdefault("_sources", set()).add(src)
            for e in entries.values():
                e["documents"] = len(e.pop("_sources", set()))
        except Exception as e:  # noqa: BLE001
            logger.debug(f"读取向量库分区统计失败: {e}")

    if not entries:
        return "(当前没有可用的知识库。请提示用户到管理后台「数据管理 → 知识库管理」创建知识库并上传文档。)"
    if not vector_ok and all(not e["chunks"] for e in entries.values()):
        return ("(知识库目录如下，但向量库当前连接失败，暂时无法检索内容：\n"
                + "\n".join(f"- **{n}**：{e['description'] or '（无描述）'}" for n, e in entries.items())
                + "\n\n请提示用户检查 Milvus 服务是否已启动。)")

    lines = ["可用知识库列表（检索时用 partition 指定名称）："]
    for name, e in entries.items():
        desc = e["description"] or "（无描述）"
        lines.append(f"- **{name}**：{desc}（{e['documents']} 篇文档 / {e['chunks']} 个切块）")
    lines.append("\n请根据上面的描述选择最相关的知识库，调用 "
                 "search_knowledge_base(partition=\"<知识库名>\", queries=[...]) 进行检索。")
    return "\n".join(lines)


@tool('search_knowledge_base', concurrent_safe=True)
def _exec_search_kb(
    partition: Annotated[str, Field(description="知识库分区名（必填，从 list_knowledge_bases 获取）")],
    queries: Annotated[list[str] | None,
                       Field(description="文本检索查询，最多 5 个；可空（仅图片检索时省略）")] = None,
    images: Annotated[list[str] | None,
                      Field(description="图片引用（MinIO 对象键或 /api/documents/image/... 直链），最多 5 个；"
                                         "可空（仅文本检索时省略）")] = None,
    top_k: Annotated[int | None, Field(description="返回结果数，默认 10，留空用默认")] = 10,
    mode: Annotated[str, Field(
        description="检索输出作用域：mixed（混合，默认）/ text（只返回文本块）/ image（只返回图片块）")] = "mixed",
) -> str:
    """语义检索指定知识库：将文本 queries 与图片 images 分别向量化后混合检索、RRF 重排，返回相关文本片段与图片直链。

    必须先通过 list_knowledge_bases 获取可用知识库，再指定 partition 参数。
    在"不知道内容在哪篇文档、按意思找”时使用；按关键词精确查证用 search_document_content，
    通读某篇文档用 read_knowledge_base_document / read_session_document。
    """
    ctx = current_tool_ctx()
    if not partition or not partition.strip():
        return "(未提供 partition 参数：必须指定知识库分区名，请先调用 list_knowledge_bases 查看可用知识库)"

    mode = (mode or "mixed").strip().lower()
    if mode not in ("mixed", "text", "image"):
        mode = "mixed"
    texts = [str(q).strip() for q in (queries or []) if str(q).strip()]
    image_refs = [str(i).strip() for i in (images or []) if str(i).strip()]
    if not texts and not image_refs:
        return "(未提供有效查询：queries（文本）与 images（图片引用）至少给其一)"

    top_k = int(top_k or 10)
    top_k = max(1, min(top_k, _cfg(ctx, "retrieval_top_k", 50)))
    logger.debug(
            "tool search_knowledge_base "
            f"partition={partition} mode={mode} texts={len(texts)} images={len(image_refs)}"
        )

    chunks = _hybrid_retrieve(
        ctx, texts, image_refs,
        retrieval_top_k=_cfg(ctx, "retrieval_top_k", 50),
        chunk_filter=mode,
        partition_filter=partition.strip(),
    )
    if not chunks:
        return f"(知识库 [{partition}] 中未检索到相关内容)"

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
    parts = [f"[{partition}] {mode_label}检索命中 {len(chunks)} 块（文本块 {n_text} + 图片块 {n_img}）"]
    if img_lines:
        parts.append("命中图片：\n" + "\n".join(img_lines))
    parts.append(formatted)
    return "\n\n".join(parts)


@tool('ocr_image', concurrent_safe=True)
def _exec_ocr_image(
    image: Annotated[str, Field(description="图片引用：MinIO 对象键或 /api/documents/image/... 直链")],
) -> str:
    """对单张图片做 OCR，识别截图/图表/扫描件中的中英文文字并返回文本。

    image 接受 MinIO 对象键或 /api/documents/image/... 直链（可用 list_session_resources 取得）。
    """
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


def _read_full_paged(ctx, source: str, filename: str, offset: int, max_chars: int | None,
                     tool_name: str, *, stem: str = "") -> str:
    """公共分页续读逻辑：从对象存储读取 ``.txt`` 全文并按 offset/max_chars 截取。

    读取后会把 ``[图:images/xxx]`` 占位替换为可渲染图片直链（前提：能定位到对象键）。
    """
    if source is None:
        logger.warning(f"tool {tool_name} 未找到: {filename}")
        return f"(未找到 {filename} 的全文，可能该文档不是由 MinerU 解析的)"
    try:
        content = source
        if stem:
            content = replace_img_placeholders(content, ctx, stem=stem)
        cache_key = f"full_text:{tool_name}:{filename}"
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
        logger.debug(f"tool {tool_name} 成功: {filename} (返回 {len(chunk)}/{total} 字符)")
        return chunk + part_info
    except Exception as e:
        logger.warning(f"tool {tool_name} 读取失败 ({filename}): {e}")
        return f"(读取 {filename} 失败: {e})"


@tool('read_knowledge_base_document')
def _exec_read_knowledge_base_document(
    filename: Annotated[str, Field(description="知识库文档名（不含扩展名）")],
    offset: Annotated[int, Field(description="字符偏移，用于分页续读")] = 0,
    max_chars: Annotated[int | None, Field(description="本次最多读取字符数")] = None,
) -> str:
    """读取知识库中某篇文档的完整正文，支持 offset/max_chars 分页续读。

    在所有知识库中按文档名查找（先用 list_knowledge_base_files 确认存在）；
    filename 为不带扩展名的文档名。会话附件请用 read_session_document。
    """
    ctx = current_tool_ctx()
    filename = (filename or "").strip()
    if not filename:
        return "(未提供 filename 参数)"
    stem = Path(filename).stem
    return _read_full_paged(ctx, _read_system_text(ctx, filename), filename, offset, max_chars,
                            "read_knowledge_base_document", stem=stem)


@tool('read_session_document')
def _exec_read_session_document(
    filename: Annotated[str, Field(description="当前会话已解析文档名（不含扩展名）")],
    offset: Annotated[int, Field(description="字符偏移，用于分页续读")] = 0,
    max_chars: Annotated[int | None, Field(description="本次最多读取字符数")] = None,
) -> str:
    """读取当前会话中已解析的上传附件的完整正文，支持 offset/max_chars 分页续读。

    filename 为不带扩展名的文档名（先用 list_session_resources 查）；知识库文档请用 read_knowledge_base_document。
    """
    ctx = current_tool_ctx()
    filename = (filename or "").strip()
    if not filename:
        return "(未提供 filename 参数)"
    stem = Path(filename).stem
    return _read_full_paged(ctx, _read_session_text(ctx, filename), filename, offset, max_chars,
                            "read_session_document", stem=stem)


@tool('list_session_resources', concurrent_safe=True)
def _exec_list_session_resources(
    pattern: Annotated[str | None, Field(description="资源名关键词过滤（可选）")] = None,
) -> str:
    """列出当前会话的资源：上传的原始文件、粘贴/附带图片、MinerU 解析出的插图与已解析文档，含对象键/直链与大小。

    可用 pattern 关键词过滤；用于查看“本会话上传了什么”并取得对象键。知识库文档请用 list_knowledge_base_files。
    """
    ctx = current_tool_ctx()
    pattern = (pattern or "").strip().lower()
    logger.debug(f"tool list_session_resources pattern={pattern!r}")

    files, pasted, docs, parsed_imgs = _list_session_resources(ctx)
    if not files and not pasted and not docs and not parsed_imgs:
        return "(当前会话还没有上传的文件、图片或已解析文档)"

    def _pfx(d: dict) -> str:
        return "🖼" if Path(d["name"]).suffix.lower() in _IMAGE_EXTS else "📄"

    def _size(n: int) -> str:
        if n < 1024:
            return f"{n}B"
        if n < 1024 * 1024:
            return f"{n / 1024:.0f}KB"
        return f"{n / 1024 / 1024:.1f}MB"

    def _fits(name: str) -> bool:
        return not pattern or pattern in name.lower()

    def _chunk_img_uri(key: str) -> str:
        return f"/api/documents/chunk_image?key={key}"

    files.sort(key=lambda x: x["name"].lower())
    pasted.sort(key=lambda x: x["name"].lower())
    parsed_imgs.sort(key=lambda x: (x["stem"].lower(), x["name"].lower()))

    lines = []
    for d in files:
        if _fits(d["name"]):
            lines.append(f"- {_pfx(d)} {d['name']}  ({_size(d['size'])})  [对象键: {d['key']}]")
    for d in pasted:
        if _fits(d["name"]):
            lines.append(f"- 🖼 {d['name']} (粘贴图片)  [对象键: {d['key']}]")
    for d in parsed_imgs:
        if _fits(d["name"]):
            lines.append(
                f"- 🖼 {d['name']} (来自 {d['stem']} 解析图)  "
                f"[对象键: {d['key']}] [直链: {_chunk_img_uri(d['key'])}]"
            )
    for d in docs:
        if _fits(d):
            lines.append(f"- 📄 {d} (已解析文档, 可用 read_session_document / search_document_content)")

    if not lines:
        return "(当前会话没有匹配的资源)"
    return "当前会话资源：\n" + "\n".join(lines)


@tool('list_knowledge_base_files', concurrent_safe=True)
def _exec_list_knowledge_base_files(
    pattern: Annotated[str | None, Field(description="文件名关键词过滤")] = None,
    sort_by: Annotated[str, Field(description="排序方式：'name' 或 'time'")] = 'name',
) -> str:
    """列出所有知识库中的文档，含所属知识库、类型/大小，含 pattern 过滤与 sort_by（name/time）排序。

    用于查看有哪些文档并取得精确文件名；需要按知识库维度浏览时先用 list_knowledge_bases；
    会话附件请用 list_session_resources。
    """
    ctx = current_tool_ctx()
    if not ctx.vector_store or not getattr(ctx.vector_store, "is_available", lambda: True)():
        return "(知识库不可用：向量库连接失败)"
    pattern = (pattern or "").strip().lower()
    logger.debug(f"tool list_knowledge_base_files pattern={pattern!r} sort={sort_by}")

    # 文档 → 所属知识库（同名文档可能分布在多个知识库）
    src_parts: dict[str, list[str]] = {}
    try:
        for m in (ctx.vector_store.metadata or []):
            src, part = m.get("source") or "", m.get("partition") or ""
            if src:
                parts = src_parts.setdefault(src, [])
                if part and part not in parts:
                    parts.append(part)
    except Exception:  # noqa: BLE001
        pass

    doc_entries = []
    for d in (ctx.vector_store.get_documents() or []):
        parts = src_parts.get(d) or []
        part = parts[0] if parts else None
        s = _get_file_stats(d, object_store=getattr(ctx, "object_store", None), partition=part)
        doc_entries.append({"name": d, "partition": part, **s})

    if pattern:
        doc_entries = [d for d in doc_entries if pattern in d["name"].lower()]

    if not doc_entries:
        return "(当前没有匹配的文档)"

    if sort_by == "time":
        doc_entries.sort(key=lambda d: (not bool(d["mtime"]), d["mtime"]), reverse=True)
    else:
        doc_entries.sort(key=lambda d: (d["name"].lower(), d["partition"] or ""))

    lines = []
    for d in doc_entries:
        info = " | ".join(p for p in [d["type"], d["size"], d["mtime"]] if p)
        head = f"- 📖 {d['name']}"
        if d["partition"]:
            head += f"　[知识库：{d['partition']}]"
        lines.append(f"{head}  ({info})" if info else head)

    return "知识库中的文档：\n" + "\n".join(lines)


@tool('read_chunk_context', concurrent_safe=True)
def _exec_read_chunk_context(
    chunk_id: Annotated[str, Field(description="目标 chunk ID")],
    before: Annotated[int, Field(description="向前取块数，上限 10")] = 3,
    after: Annotated[int, Field(description="向后取块数，上限 10")] = 3,
) -> str:
    """按 chunk ID 读取该块及其前后相邻块以补全上下文（目标块以【目标】标记）。

    chunk ID 取自 search_knowledge_base 的检索结果。
    """
    ctx = current_tool_ctx()
    chunk_id = (chunk_id or "").strip()
    before = before
    after = after
    before = min(max(int(before), 0), 10)
    after = min(max(int(after), 0), 10)

    if not chunk_id:
        return "(未提供 chunk_id 参数)"

    if not ctx.vector_store or not getattr(ctx.vector_store, "is_available", lambda: True)():
        return "(知识库不可用：向量库连接失败)"

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
    """在所有知识库与会话附件的全文（txt）中按关键词精确匹配，返回命中文档名与所在行片段。

    适合查具体数字/名称/术语的确切出处；语义模糊时改用 search_knowledge_base，source 可限定单篇文档名。
    """
    ctx = current_tool_ctx()
    keyword = (keyword or "").strip()
    if not keyword:
        return "(未提供 keyword 参数)"
    source_filter = (source or "").strip().lower()
    max_results = min(int(max_results), 50)

    logger.debug(f"tool search_document_content keyword={keyword!r} source={source_filter!r}")

    if not ctx.vector_store or not getattr(ctx.vector_store, "is_available", lambda: True)():
        return "(知识库不可用：向量库连接失败)"

    try:
        kb_docs = ctx.vector_store.get_documents() or []
    except Exception:
        kb_docs = []

    if source_filter:
        doc_names = [source_filter]
    else:
        # 所有知识库文档 + 当前会话已解析的上传附件（不进向量库）
        doc_names = list(dict.fromkeys(kb_docs + _list_session_docs(ctx)))

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
