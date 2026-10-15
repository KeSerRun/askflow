"""agent.tools._common —— 工具 handler 的公共辅助（各工具实现共享）。

知识库 / 联网 / 基础设施的辅助函数与常量、以及检索片段格式化（_format）集中在这里；
handler 模块（_kb/_web/_infra）只保留 @tool 工具入口，辅助从本模块导入。
"""

from __future__ import annotations

import html as _html
import re as _re
import urllib.parse
from pathlib import Path

from core.models import Document
from infra.util.logger import logger
from modules.document.backend import match_img_key

SYSTEM_PARTITION = "__system__"


def _format_chunk(idx: int, chunk: Document) -> str:
    """格式化单个检索块为带元数据的文本（来源/章节/页码/类型 + 图片引用）。"""
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
        parts.append("📖 系统文档")
    elif partition:
        parts.append("📄 用户文档")
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


def format_retrieved_chunks(chunks: list[Document]) -> str:
    """将一组检索块拼接为完整上下文文本，并附 read_chunk_context 调用提示。"""
    if not chunks:
        return ""
    text = "\n\n".join(_format_chunk(i + 1, c) for i, c in enumerate(chunks))

    ids = set()
    for c in chunks[:3]:
        cid = (c.metadata.get("id") or "")[:8]
        if cid:
            ids.add(cid)
    if ids:
        example_id = next(iter(ids))
        text += (
            "\n\n---\n"
            "💡 如需查看某个片段前后的更多上下文，可调用 "
            f'read_chunk_context(chunk_id="{example_id}", before=3, after=3)'
        )
    return text

# ── 公共基础设施（配置 / 缓存） ──


def _cfg(ctx, key: str, default=None):
    """从 ctx.config 读取配置（无全局回退）。

    Args:
        ctx: ToolContext（须携带 config）。
        key: 配置属性名。
        default: 配置对象缺少该属性时的兜底值。

    Returns:
        配置值。
    """
    config = getattr(ctx, "config", None)
    if config is None:
        return default
    return getattr(config, key, default)


def _cache_get(ctx, key: str):
    """从注入的缓存读取（无缓存实例返回 None）。"""
    cache = getattr(ctx, "cache", None)
    return cache.get(key) if cache else None


def _cache_set(ctx, key: str, value, *, ttl: int = 300) -> None:
    """写入注入的缓存（无缓存实例则忽略）。"""
    cache = getattr(ctx, "cache", None)
    if cache:
        cache.set(key, value, ttl=ttl)


# ── 会话附件（对话页上传 → MinerU 解析为 txt，不入向量库；从对象存储读取） ──


def _store(ctx):
    """注入的对象存储适配器（无则返回 None）。"""
    return getattr(ctx, "object_store", None)


def _iter_keys(store, prefix: str):
    """迭代对象存储 prefix 下的键（异常时静默返回空）。"""
    if store is None:
        return
    try:
        yield from store.list_keys(prefix)
    except Exception:  # noqa: BLE001
        return


def _first_text_key(store, prefix: str) -> str | None:
    """在 prefix 下找第一个 ``.txt`` 正文文件键。"""
    for k in _iter_keys(store, prefix):
        if k.lower().endswith(".txt"):
            return k
    return None


def _session_ns(ctx) -> str:
    """当前会话对象前缀：``sessions/{partition}/{session_id}``（缺上下文返回空）。"""
    part = (getattr(ctx, "partition", "") or "").strip()
    sid = (getattr(ctx, "session_id", "") or "").strip()
    if not (part and sid):
        return ""
    return f"sessions/{str(part).lower()}/{Path(sid).name}"


def _read_session_text(ctx, filename: str) -> str | None:
    """读取当前会话内由 MinerU 解析出的正文文本（从对象存储，读 ``.txt``）。"""
    ns = _session_ns(ctx)
    store = _store(ctx)
    if not ns or not store:
        return None
    key = _first_text_key(store, f"{ns}/chunk_out/{Path(filename).stem}")
    if key is None:
        return None
    data = store.get_bytes(key)
    return data.decode("utf-8", errors="replace") if data else None


def replace_img_placeholders(text: str, ctx, *, stem: str) -> str:
    """把正文中 ``[图:images/img_0001.png]`` 占位替换为可渲染 markdown 图片直链。

    会话/知识库解析文里图的位置只有占位符，替换成 ``![图](直链)`` 后，
    模型即可在回答中展示真实插图；无法定位到图片时保留原占位。

    Args:
        text: MinerU 渲染的纯文本正文。
        ctx: ToolContext（含 object_store / partition / session_id）。
        stem: 文档 stem（不含扩展名），用于定位 ``chunk_out/{stem}/images/``。

    Returns:
        替换后的正文。
    """
    import re as _re

    if not text or "[图:" not in text:
        return text
    ns = _session_ns(ctx)
    store = _store(ctx)
    if store is None:
        return text

    def _resolve(img_name: str) -> str | None:
        img_name = img_name.strip()
        if not img_name:
            return None
        # 会话附件优先
        if ns:
            try:
                for k in _iter_keys(store, f"{ns}/chunk_out/{Path(stem).stem}"):
                    if match_img_key(k, img_name):
                        return k
            except Exception:  # noqa: BLE001
                pass
        # 其次系统文档
        try:
            for k in _iter_keys(store, f"uploads/{SYSTEM_PARTITION}/chunk_out/{Path(stem).stem}"):
                if match_img_key(k, img_name):
                    return k
        except Exception:  # noqa: BLE001
            pass
        return None

    def _sub(m: _re.Match) -> str:
        img_ref = m.group(1).strip()
        key = _resolve(img_ref.split("/")[-1]) if "/" in img_ref else _resolve(img_ref)
        if key:
            return f"![图](/api/documents/chunk_image?key={key})"
        return m.group(0)

    return _re.sub(r"\[图:\s*([^\]]+)\]", _sub, text)


def _list_session_docs(ctx) -> list[str]:
    """列出当前会话已成功解析（含正文产物）的文档名（stem，不含扩展名）。"""
    ns = _session_ns(ctx)
    store = _store(ctx)
    if not ns or not store:
        return []
    prefix = f"{ns}/chunk_out/"
    stems: set[str] = set()
    for k in _iter_keys(store, prefix):
        tail = k[len(prefix):]
        if "/" not in tail:
            continue
        seg = tail.split("/", 1)[1]
        if seg.lower().endswith(".txt"):
            stems.add(tail.split("/", 1)[0])
    return sorted(stems)


_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff"}


def _list_session_resources(
    ctx,
) -> tuple[list[dict], list[dict], list[str], list[dict]]:
    """枚举当前会话资源，返回 ``(直接文件, 粘贴图片, 已解析文档, 解析图片)``。

    - 直接文件：``sessions/{partition}/{session_id}/{name}`` 下的原始附件（含图片文件），
      ``{"name", "size", "key"}``；
    - 粘贴图片：``{ns}/query_img/*``，``{"name", "key"}``；
    - 已解析文档：见 :func:`_list_session_docs`（stem，可配 read_session_document / search_document_content）；
    - 解析图片：``{ns}/chunk_out/{stem}/images/*``，``{"name", "key", "stem"}``
      （MinerU 从附件中抽取的插图；可用 ocr_image / search_knowledge_base(images) 处理）。
    """
    ns = _session_ns(ctx)
    store = _store(ctx)
    files: list[dict] = []
    pasted: list[dict] = []
    parsed_imgs: list[dict] = []
    if ns and store:
        try:
            for key, size in store.list_objects(f"{ns}/"):
                tail = key[len(ns) + 1:]
                if not tail or "/" in tail:
                    continue  # 嵌套产物（chunk_out / query_img 等）不属于直接文件
                files.append({"name": tail, "size": size, "key": key})
        except Exception:  # noqa: BLE001
            pass
        try:
            for key in _iter_keys(store, f"{ns}/query_img/"):
                name = key.rsplit("/", 1)[-1]
                if name:
                    pasted.append({"name": name, "key": key})
        except Exception:  # noqa: BLE001
            pass
        try:
            for key in _iter_keys(store, f"{ns}/chunk_out/"):
                if "/images/" not in key:
                    continue
                name = key.rsplit("/", 1)[-1]
                if not name:
                    continue
                stem = key.split("/chunk_out/", 1)[1].split("/", 1)[0]
                parsed_imgs.append({"name": name, "key": key, "stem": stem})
        except Exception:  # noqa: BLE001
            pass
    files.sort(key=lambda d: d["name"].lower())
    pasted.sort(key=lambda d: d["name"].lower())
    parsed_imgs.sort(key=lambda d: (d["stem"].lower(), d["name"].lower()))
    return files, pasted, _list_session_docs(ctx), parsed_imgs


# ── 知识库辅助 ──


_RRF_K_DEFAULT = 60


def rrf_rerank(
    ranked_results: list[tuple[int, int, Document]],
    k: int = _RRF_K_DEFAULT,
    top_n: int | None = None,
) -> list[Document]:
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


def _read_system_text(ctx, filename: str) -> str | None:
    """读取系统分区文档的全文（从对象存储，读 ``.txt``，仅 ``__system__`` 分区）。"""
    store = _store(ctx)
    if store is None:
        return None
    stem = Path(filename).stem
    key = _first_text_key(store, f"uploads/{SYSTEM_PARTITION}/chunk_out/{stem}")
    if key is None:
        return None
    data = store.get_bytes(key)
    return data.decode("utf-8", errors="replace") if data else None


def _read_doc_text(ctx, filename: str) -> str | None:
    """读取文档全文：系统分区优先，其次当前会话附件（均从对象存储）。"""
    text = _read_system_text(ctx, filename)
    if text is not None:
        return text
    return _read_session_text(ctx, filename)


def _get_file_stats(filename: str, *, object_store: object = None) -> dict:
    """获取系统分区文档的元信息（大小、修改时间、类型）。

    Args:
        filename: 文档文件名。
        object_store: 对象存储适配器（读取正文大小）。

    Returns:
        包含 'size'、'mtime'、'type' 三个键的字典，各字段可能为空字符串。
    """
    stats = {"size": "", "mtime": "", "type": ""}
    if object_store is not None:
        stem = Path(filename).stem
        key = _first_text_key(object_store, f"uploads/{SYSTEM_PARTITION}/chunk_out/{stem}")
        if key:
            data = object_store.get_bytes(key)
            if data:
                size = len(data)
                if size < 1024:
                    stats["size"] = f"{size}B"
                elif size < 1024 * 1024:
                    stats["size"] = f"{size / 1024:.0f}KB"
                else:
                    stats["size"] = f"{size / 1024 / 1024:.1f}MB"
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


def _resolve_image_bytes(ctx, ref: str):
    """把图片引用解析为字节：支持 MinIO 对象键、``/api/documents/image/...`` 直链、
    ``/api/documents/chunk_image?key=...`` 直链（会话 / 知识库 MinerU 解析图）。

    Args:
        ctx: ToolContext（需携带 object_store）。
        ref: 图片引用（对象键 / 直链 URL）。

    Returns:
        图片字节；解析失败返回 None。
    """
    ref = (ref or "").strip(' "`')
    store = _store(ctx)
    if not ref or store is None:
        return None

    if ref.startswith("/api/documents/chunk_image"):
        # 会话/知识库 MinerU 解析图直链：chunk_image?key=<对象键>
        q = ref.split("?", 1)[1] if "?" in ref else ""
        key = ""
        for pair in q.split("&"):
            if pair.startswith("key="):
                key = pair[4:]
                break
        key = key.lstrip("/")
        if not key or "/chunk_out/" not in key or "/images/" not in key:
            return None
        try:
            return store.get_bytes(key)
        except Exception:  # noqa: BLE001
            return None

    if ref.startswith("/api/documents/image/"):
        rest = ref[len("/api/documents/image/"):]
        segs = rest.split("/", 1)
        if len(segs) != 2:
            return None
        stem, img_name = segs
        for k in _iter_keys(store, f"uploads/{SYSTEM_PARTITION}/chunk_out/{Path(stem).stem}"):
            if match_img_key(k, img_name):
                return store.get_bytes(k)
        return None

    if "://" in ref or ref.startswith("/"):
        return None
    try:
        return store.get_bytes(ref.lstrip("/"))
    except Exception:  # noqa: BLE001
        return None


def _hybrid_retrieve(
    ctx,
    texts: list[str],
    image_refs: list[str],
    retrieval_top_k: int | None = None,
    top_n: int | None = None,
    chunk_filter: str = "mixed",
) -> list[Document]:
    """多模态混合检索：文本与图片各自向量化检索，按 RRF 重排融合。

    - 每个文本 query → ``search``（文本嵌入）；
    - 每个图片引用 → ``embed_image_bytes`` + ``search_by_vector``（图向量，同空间）；
    - 全部结果按 RRF 合并去重；
    - ``chunk_filter`` 控制**输出作用域**：``text`` 只保留文本块，``image`` 只保留图块，
      ``mixed`` 全部保留（输入 queries/images 不受其影响）。

    Args:
        ctx: ToolContext（含 vector_store / object_store）。
        texts: 文本检索查询列表。
        image_refs: 图片引用列表（对象键或直链）。
        retrieval_top_k: 单个 query 的候选数。
        top_n: 返回前 N 条；None 返回全部。
        chunk_filter: 输出块类型过滤（"mixed" / "text" / "image"）。

    Returns:
        按 RRF 分数降序排列的 Document 列表（含 source/chunk_type/img_path）。
    """
    vs = getattr(ctx, "vector_store", None)
    if vs is None or not getattr(vs, "is_available", lambda: True)():
        return []
    k = int(retrieval_top_k or 50)
    all_ranked: list[tuple[int, int, Document]] = []
    qid = 0

    for q in texts:
        if not str(q).strip():
            qid += 1
            continue
        try:
            results = vs.search(query=str(q), top_k=k, chunk_filter=chunk_filter) or []
        except Exception as e:
            logger.error(f"文本检索失败 (q={q!r}): {e}")
            results = []
        for rank, doc in enumerate(results, 1):
            all_ranked.append((qid, rank, doc))
        qid += 1

    for ref in image_refs:
        data = _resolve_image_bytes(ctx, ref)
        if data is None:
            logger.warning(f"图片引用解析失败，跳过: {str(ref)[:60]}")
            qid += 1
            continue
        try:
            vec = vs.embed_image_bytes(data)
            results = vs.search_by_vector(vec, top_k=k, chunk_filter=chunk_filter) or []
        except Exception as e:
            logger.error(f"图片检索失败 ({str(ref)[:40]}): {e}")
            results = []
        for rank, doc in enumerate(results, 1):
            all_ranked.append((qid, rank, doc))
        qid += 1

    if not all_ranked:
        logger.debug("多模态检索未命中, 返回 0 块")
        return []

    merged = rrf_rerank(all_ranked, top_n=top_n)
    if chunk_filter == "text":
        merged = [d for d in merged
                  if str((d.metadata or {}).get("chunk_type", "")).strip() == "text"]
    elif chunk_filter == "image":
        merged = [d for d in merged
                  if str((d.metadata or {}).get("chunk_type", "")).strip() in ("image", "chart")]
    logger.debug(f"多模态混合检索完成: {len(texts)} 文本 + {len(image_refs)} 图片 "
                 f"→ {len(merged)} 块 (filter={chunk_filter})")
    return merged


# ── 联网辅助 ──


_DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


_MAX_REDIRECTS = 5


_MAX_READ_CHARS = 50_000


_JINA_READER_URL = "https://r.jina.ai"


def _is_private_ip(ip: str) -> bool:
    """检查 IP 是否为内网 / 保留地址。

    覆盖 RFC 1918（10/8, 172.16/12, 192.168/16）、
    loopback（127/8）、link-local（169.254/16）、以及广播地址。

    Args:
        ip: 点分十进制 IP 字符串。

    Returns:
        如果是内网或保留地址返回 True，否则返回 False。
    """
    parts = ip.split(".")
    if len(parts) != 4:
        return False
    try:
        first = int(parts[0])
    except ValueError:
        return False
    if first == 10:
        return True
    if first == 172 and 16 <= int(parts[1]) <= 31:
        return True
    if first == 192 and parts[1] == "168":
        return True
    if first in (127, 0):
        return True
    if ip == "255.255.255.255" or ip.startswith("169.254."):
        return True
    return False


def _validate_url_target(url: str) -> str | None:
    """验证单个 URL 目标是否安全。

    检查 scheme 是否仅允许 http/https，并解析 DNS 排查内网地址。

    Args:
        url: 待验证的 URL。

    Returns:
        None 表示通过，字符串为错误原因。
    """
    import socket

    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return f"不支持的协议: {parsed.scheme}（仅允许 http/https）"
    host = parsed.hostname or ""
    try:
        ip = socket.gethostbyname(host)
    except socket.gaierror:
        ip = host
    if _is_private_ip(ip):
        return f"禁止访问内网地址: {url}"
    return None


def _validate_url_chain(initial_url: str) -> tuple[str | None, str | None]:
    """验证并解析重定向链，返回最终可达 URL（委托 _fetch_url）。

    SSRF / 重定向防护统一由 ``_fetch_url`` 实现（逐跳校验 + 环检测 + 次数上限）。

    Args:
        initial_url: 初始 URL。

    Returns:
        (final_url, error) 二元组。通过时 error 为 None；失败时 final_url 为 None。
    """
    resp, error = _fetch_url((initial_url or "").strip(" \t\r\n`\"'"))
    if error or resp is None:
        return None, error or "请求失败"
    try:
        return str(resp.url), None
    finally:
        resp.close()


def _fetch_url(target: str) -> tuple:
    """安全地获取 URL 内容（含重定向链验证）。

    逐跳验证每个跳转 URL 的安全性，防止 SSRF。

    Args:
        target: 要获取的 URL。

    Returns:
        (response_or_none, error_or_none) 二元组。
        成功时 error 为 None，失败时 response 为 None。
    """
    import socket

    import httpx

    current = target
    seen = set()

    for _ in range(_MAX_REDIRECTS + 1):
        err = _validate_url_target(current)
        if err:
            return None, err

        parsed = urllib.parse.urlparse(current)
        try:
            socket.gethostbyname(parsed.hostname or "")
        except socket.gaierror:
            return None, f"DNS 解析失败: {parsed.hostname}"

        try:
            resp = httpx.get(
                current,
                follow_redirects=False,
                timeout=30,
                headers={"User-Agent": _DEFAULT_USER_AGENT},
            )
        except Exception as e:
            return None, f"请求失败: {e}"

        if not (300 <= resp.status_code < 400):
            return resp, None

        location = resp.headers.get("location")
        if not location:
            return resp, None

        next_url = urllib.parse.urljoin(current, location)
        if next_url in seen:
            resp.close()
            return None, "检测到重定向环"
        seen.add(next_url)
        current = next_url
        resp.close()

    return None, f"重定向次数超过限制 ({_MAX_REDIRECTS})"


def _try_jina_reader(url: str, jina_key: str = "") -> str | None:
    """通过 Jina Reader API 提取页面内容（Markdown 格式）。

    优先尝试 Jina Reader（https://r.jina.ai），如果配置了 API Key 则附加 Bearer 认证。

    Args:
        url: 目标网页 URL。
        jina_key: 注入的 API Key（空则回退全局配置）。

    Returns:
        提取的 Markdown 文本，失败时返回 None。
    """
    try:
        import httpx

        headers = {"Accept": "application/json"}
        if jina_key:
            headers["Authorization"] = f"Bearer {jina_key}"

        resp = httpx.get(
            f"{_JINA_READER_URL}/{url}",
            headers=headers,
            timeout=20,
        )
        if resp.status_code != 200:
            logger.debug(f"Jina Reader 返回 {resp.status_code}, 跳过")
            return None

        data = resp.json().get("data", {})
        text = data.get("content", "")
        if not text:
            return None

        title = data.get("title", "")
        if title:
            text = f"# {title}\n\n{text}"

        truncated = len(text) > _MAX_READ_CHARS
        if truncated:
            text = text[:_MAX_READ_CHARS]

        if truncated:
            text += "\n\n...(内容过长，已截取)"
        return text

    except Exception as e:
        logger.debug(f"Jina Reader 失败: {e}")
        return None


def _try_readability(url: str) -> str | None:
    """使用 readability-lxml 本地解析 HTML → Markdown。

    作为 Jina Reader 失败时的回退方案。

    Args:
        url: 目标网页 URL。

    Returns:
        提取的 Markdown 文本，失败时返回 None。
    """
    try:
        from readability import Document
    except ImportError:
        logger.debug("readability-lxml 未安装")
        return None

    resp, error = _fetch_url(url)
    if error or resp is None:
        return None

    try:
        doc = Document(resp.text)
        summary = doc.summary()
        text = _html_to_markdown(summary)

        title = doc.title()
        if title:
            text = f"# {title}\n\n{text}"

        truncated = len(text) > _MAX_READ_CHARS
        if truncated:
            text = text[:_MAX_READ_CHARS]

        if truncated:
            text += "\n\n...(内容过长，已截取)"
        return text

    except Exception as e:
        logger.debug(f"readability 解析失败: {e}")
        return None
    finally:
        resp.close()


def _try_raw_html(url: str) -> str | None:
    """兜底方案：下载 HTML 后 strip 标签。

    当 Jina Reader 和 readability 都不可用时，使用 raw HTML 提取纯文本。

    Args:
        url: 目标网页 URL。

    Returns:
        提取的纯文本，失败时返回 None。
    """
    resp, error = _fetch_url(url)
    if error or resp is None:
        return None

    try:
        from html.parser import HTMLParser as _HTMLParser

        class _TextExtractor(_HTMLParser):
            """HTMLParser 子类，提取所有可见文本。

            跳过 <script> 和 <style> 块的内容，
            在块级标签结束处插入换行以保留段落结构。
            """

            def __init__(self):
                """初始化提取器状态。"""
                super().__init__()
                self._text = []
                self._skip = False

            def get_text(self) -> str:
                """返回提取的完整文本。"""
                return "".join(self._text)

        extractor = _TextExtractor()
        extractor.feed(resp.text)
        text = extractor.get_text()
        text = _re.sub(r"\n{3,}", "\n\n", text).strip()

        truncated = len(text) > _MAX_READ_CHARS
        if truncated:
            text = text[:_MAX_READ_CHARS]
        if truncated:
            text += "\n\n...(内容过长，已截取)"
        return text

    except Exception as e:
        logger.debug(f"raw HTML 提取失败: {e}")
        return None
    finally:
        resp.close()


def _html_to_markdown(html: str) -> str:
    """简单的 HTML → Markdown 转换。

    处理标签：a（转链接）、h1-h6（转 # 标题）、li（转列表项）、
    p/div/section/article（转段落）、br/hr（转换行）。

    Args:
        html: 原始 HTML 字符串。

    Returns:
        转换后的 Markdown 文本。
    """
    text = _re.sub(
        r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>([\s\S]*?)</a>',
        lambda m: f'[{_strip_tags(m.group(2))}]({m.group(1)})',
        html, flags=_re.I,
    )
    text = _re.sub(
        r'<h([1-6])[^>]*>([\s\S]*?)</h\1>',
        lambda m: f'\n{"#" * int(m.group(1))} {_strip_tags(m.group(2))}\n',
        text, flags=_re.I,
    )
    text = _re.sub(
        r'<li[^>]*>([\s\S]*?)</li>',
        lambda m: f'\n- {_strip_tags(m.group(1))}',
        text, flags=_re.I,
    )
    text = _re.sub(r'</(p|div|section|article)>', '\n\n', text, flags=_re.I)
    text = _re.sub(r'<(br|hr)\s*/?>', '\n', text, flags=_re.I)
    text = _normalize_ws(_strip_tags(text))
    return text


def _strip_tags(text: str) -> str:
    """去除 HTML 标签并解码 HTML 实体。

    先移除 script 和 style 块，再移除所有剩余标签。

    Args:
        text: 含 HTML 标签的文本。

    Returns:
        纯文本，HTML 实体已被解码。
    """
    text = _re.sub(r'<script[\s\S]*?</script>', '', text, flags=_re.I)
    text = _re.sub(r'<style[\s\S]*?</style>', '', text, flags=_re.I)
    text = _re.sub(r'<[^>]+>', '', text)
    return _html.unescape(text).strip()


def _normalize_ws(text: str) -> str:
    """归一化空白字符。

    将连续的空白字符（空格 / 制表符）替换为单个空格，
    将连续 3 个及以上的换行替换为双换行。

    Args:
        text: 待归一化的文本。

    Returns:
        归一化后的文本。
    """
    text = _re.sub(r'[ \t]+', ' ', text)
    return _re.sub(r'\n{3,}', '\n\n', text).strip()


def _search_searxng(query: str, max_results: int, *,
                    searxng_url: str,
                    timeout: float) -> list | None:
    """SearXNG — 开源元搜索引擎。

    通过配置的 searxng_url 发起 JSON 格式搜索。

    Args:
        query: 搜索关键词。
        max_results: 最大结果数。
        searxng_url: 服务地址（必填，由调用方注入）。
        timeout: 超时秒数。

    Returns:
        结果列表，每个结果含 title/body/href 键。失败时返回 None。
    """
    base_url = searxng_url.rstrip("/")
    if not base_url:
        logger.warning("[tool] searxng_url 未配置")
        return None

    try:
        import requests as _req
        params = {"q": query, "format": "json", "language": "zh-CN"}
        resp = _req.get(
            f"{base_url}/search",
            params=params,
            timeout=timeout,
            headers={"User-Agent": _DEFAULT_USER_AGENT},
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning(f"tool SearXNG 搜索失败: {e}")
        return None

    results = data.get("results", [])
    out = []
    for r in results[:max_results]:
        out.append({
            "title": r.get("title", ""),
            "body": r.get("content", ""),
            "href": r.get("url", ""),
        })
    return out


# ── 基础设施辅助（会话目标等） ──


_GOAL_CACHE: dict[str, str] = {}


def _get_goal_line(sid: str) -> str:
    """读取当前活跃目标文本，仅查内存缓存。

    用于组装 system prompt 中的目标信息行。

    Args:
        sid: 会话 ID。

    Returns:
        格式如 '\\n# 当前目标：xxx' 的字符串，无活跃目标时返回空字符串。
    """
    goal = _GOAL_CACHE.get(sid)
    if goal:
        return f"\n# 当前目标：{goal}"
    return ""


# ── 规划期任务清单（todolist，内存缓存，随工具事件实时同步前端） ──

_TODO_CACHE: dict[str, list[dict]] = {}


def _get_todolist(sid: str) -> list[dict]:
    """读当前会话任务清单（[{id, text, done}]，空则 []）。"""
    return list(_TODO_CACHE.get(sid, []))


def _set_todolist(sid: str, items: list) -> list[dict]:
    """设置/覆盖会话任务清单（规划期调用）。跳过空文本项。"""
    lst: list[dict] = []
    for i, it in enumerate(items or []):
        if isinstance(it, dict):
            text = str(it.get("text") or "").strip()
            todo_id = str(it.get("id") or f"todo-{i + 1}")
        else:
            text = str(it or "").strip()
            todo_id = f"todo-{i + 1}"
        if not text:
            continue
        lst.append({"id": todo_id, "text": text, "done": bool(it.get("done")) if isinstance(it, dict) else False})
    if lst:
        _TODO_CACHE[sid] = lst
    else:
        _TODO_CACHE.pop(sid, None)
    return lst


def _check_todo(sid: str, todo_id: str, done: bool = True) -> bool:
    """把清单中某项标记为完成/未完成；找到返回 True。"""
    lst = _TODO_CACHE.get(sid)
    if not lst:
        return False
    for it in lst:
        if it["id"] == todo_id:
            it["done"] = bool(done)
            return True
    return False


def _todo_line(sid: str) -> str:
    """组装 system prompt 里的任务清单行（供后续回合模型保持感知）。"""
    lst = _TODO_CACHE.get(sid)
    if not lst:
        return ""
    lines = ["\n# 当前任务清单："] + [
        f"- [{'x' if it['done'] else ' '}] {i + 1}. {it['text']}"
        for i, it in enumerate(lst)
    ]
    return "\n".join(lines)
