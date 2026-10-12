# ── MinerU 本地化 PDF 解析 ────────────────────────────────────────
"""MinerU 本地化解析：V1 API 客户端（单文件）→ 内容分块 → 文档加载器。

对接自托管 MinerU 4.x 的 V1 协议（/v1/openapi；仅单文件）：
  1. POST /v1/uploads                     → 创建上传，拿上传 URL/方法/头
  2. PUT  上传 URL（同源相对地址按基础地址补齐）
  3. POST /v1/uploads/{id}/complete       → 完成上传，取得 file_id
  4. POST /v1/parse/jobs                  → 提交单文件解析任务（tier/输出格式）
  5. GET  /v1/parse/jobs/{job_id}         → 轮询至终态
  6. GET  /v1/files/{file_id}/content     → 下载 middle_json / zip 产物

已被移除：云端 v4 的 file-urls/batch → 预签名上传 → 批量轮询 → ZIP 下载整条链路。
"""

from __future__ import annotations

import base64
import json
import re
import time
from pathlib import Path
from typing import Iterator, TYPE_CHECKING

import requests

from config import conf
from infra.util.logger import logger

if TYPE_CHECKING:
    from core.models import Document

# ── 上传 MIME 映射（按扩展名；MinerU 主要靠 filename 判定类型，MIME 兜底） ──

_MIME_BY_EXT = {
    "pdf": "application/pdf",
    "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
    "webp": "image/webp", "bmp": "image/bmp", "tif": "image/tiff",
    "tiff": "image/tiff", "gif": "image/gif", "ico": "image/x-icon",
    "doc": "application/msword",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "ppt": "application/vnd.ms-powerpoint",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "xls": "application/vnd.ms-excel",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


def _mime_of(filename: str) -> str:
    """按文件名扩展名选择 MIME 类型，未知格式回退 octet-stream。"""
    ext = Path(filename or "").suffix.lstrip(".").lower()
    return _MIME_BY_EXT.get(ext, "application/octet-stream")


_MIME_EXT_ALIAS = {"jpeg": "jpg", "svg+xml": "svg", "tiff": "tiff", "tif": "tif"}


def _find_image_base64(node) -> str | None:
    """在 block 内递归查找 ``image_base64`` data-URI。"""
    if isinstance(node, dict):
        val = node.get("image_base64")
        if isinstance(val, str) and val.startswith("data:image/"):
            return val
        for v in node.values():
            hit = _find_image_base64(v)
            if hit:
                return hit
    elif isinstance(node, list):
        for v in node:
            hit = _find_image_base64(v)
            if hit:
                return hit
    return None


def _write_images_from_json(pages: list, out_dir: Path, zip_path: Path | None = None) -> list[str]:
    """在删除 image_base64 前，先把 middle_json 图块解码落盘为 ``images/img_NNNN.ext``。

    图片来源依次尝试：
    1. 块内 ``image_base64``（PPT/DOCX 常见）；
    2. MinerU 产物 zip 内的 ``images/page_{page_idx}_{image|chart}_{index}.ext``（PDF 常见，
       middle_json 不含图数据，图以独立文件形式随 zip 返回）。

    并按块顺序给每个 image/chart 块回填 ``img_path``（供 txt 渲染 / md_view 使用），
    返回按块顺序的图片路径列表（与 chunk_pages 的 image/chart 消费顺序一致）。
    """
    imgs_dir = out_dir / "images"
    imgs_dir.mkdir(parents=True, exist_ok=True)

    zip_refs: dict[str, object] = {}
    if zip_path is not None and Path(zip_path).is_file():
        import zipfile

        try:
            zf = zipfile.ZipFile(zip_path)
            for n in zf.namelist():
                if n.startswith("images/"):
                    zip_refs[n] = zf
        except Exception:  # noqa: BLE001
            zip_refs = {}

    def _read_from_zip(page_idx: int, typ: str, index) -> tuple[bytes | None, str]:
        prefix = "chart" if typ == "chart" else "image"
        want = f"images/page_{page_idx}_{prefix}_{index}"
        for n, zf in zip_refs.items():
            if n.startswith(want + "."):
                try:
                    data = zf.read(n)
                except Exception:  # noqa: BLE001
                    return None, "jpg"
                ext = n.rsplit(".", 1)[-1].lower()
                if ext in ("jpg", "jpeg"):
                    ext = "jpg"
                return data, ext
        return None, "jpg"

    img_paths: list[str] = []
    idx = 0
    for page in pages or []:
        page_idx = page.get("page_idx") or 0
        for block in page.get("blocks") or []:
            typ = str(block.get("type", "")).lower()
            if typ not in ("image", "chart"):
                continue
            idx += 1
            uri = _find_image_base64(block)
            raw = None
            ext = "jpg"
            if uri:
                m = re.search(r"data:image/([a-z0-9+.-]+);base64,", uri)
                if m:
                    ext = _MIME_EXT_ALIAS.get(m.group(1).lower(), m.group(1).lower())
                try:
                    raw = base64.b64decode(uri.split(",", 1)[1])
                except Exception:  # noqa: BLE001
                    raw = None
            if raw is None:
                raw, ext = _read_from_zip(page_idx, typ, block.get("index") or 0)
            name = f"img_{idx:04d}.{ext}"
            if raw:
                try:
                    (imgs_dir / name).write_bytes(raw)
                except OSError:
                    pass
            img_path = f"images/{name}"
            block["img_path"] = img_path
            img_paths.append(img_path)
    return img_paths


def _strip_json_base64(work_dir: Path, img_paths: list | None = None) -> int:
    """移除 middle_json 中 image/chart 块的 ``image_base64`` 内联编码（图片已抽成文件）。

    可选传入 ``img_paths``：按块顺序给每个 image/chart 块回填 ``img_path``（图片 ID），
    使文本渲染 / md_view 能对应到具体图片文件。

    Returns:
        移除的字段数量。
    """
    removed = 0
    idx = 0
    paths = list(img_paths or [])

    def _walk(node):
        nonlocal removed, idx
        if isinstance(node, dict):
            if isinstance(node.get("image_base64"), str) \
                    and node["image_base64"].startswith("data:image/"):
                del node["image_base64"]
                removed += 1
            typ = str(node.get("type", "")).lower()
            if typ in ("image", "chart"):
                if idx < len(paths):
                    node["img_path"] = paths[idx]
                idx += 1
            for v in node.values():
                _walk(v)
        elif isinstance(node, list):
            for v in node:
                _walk(v)

    for path in sorted(Path(work_dir).rglob("*.middle_json.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        before = removed
        injected = idx
        _walk(data)
        if removed > before or idx != injected:
            try:
                path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            except OSError:
                pass
    return removed


def _render_document_text(pages: list, doc_title: str = "") -> str:
    """把 middle_json 的 pages/blocks 渲染成纯文本（供 read_full_document / 关键词检索）。

    跳过页眉/页脚/页码；标题块 → ``# 标题``；表格 → Markdown 表格；
    图/表块 → ``[图:images/img_NNNN.ext]``（有标题则 ``[图:xxxx] 标题``）。
    """
    lines: list[str] = []
    for page in pages or []:
        for block in page.get("blocks") or []:
            typ = str(block.get("type", "")).lower()
            if typ in _SKIP_BLOCK_TYPES:
                continue
            if typ in ("doc_title", "paragraph_title"):
                txt = _runs_to_text(block.get("content") or "").strip()
                if txt:
                    lines.append(f"# {txt}")
            elif typ == "table":
                cap = _block_text(block).strip()
                html = _block_table_html(block)
                body = _table_html_to_md(html) if html else ""
                seg = ("\n".join(p for p in (cap, body) if p)) or "(表格)"
                lines.append(seg)
            elif typ in ("chart", "image"):
                cap = _block_text(block).strip()
                ip = (block.get("img_path") or "").strip()
                if cap:
                    lines.append(f"[图:{ip}] {cap}" if ip else f"[图] {cap}")
                else:
                    lines.append(f"[图:{ip}]" if ip else "[图]")
            else:
                txt = _runs_to_text(block.get("content") or "").strip()
                if txt:
                    lines.append(txt)
    return "\n\n".join(p for p in lines if p)


# ── 异常定义 ──────────────────────────────────────────────────────


class MinerUError(Exception):
    """MinerU API 调用异常。"""
    pass


# ── 本地 V1 客户端（单文件） ──────────────────────────────────────


class MinerUClient:
    """本地 MinerU 4.x V1 API 客户端，单文件同步解析一个 PDF。

    流程：创建上传 → 传字节 → 完成上传 → 建解析任务（单文件）→ 轮询 → 下载产物。
    """

    def __init__(self, base_url: str, token: str | None = None, tier: str = "basic"):
        """初始化。

        Args:
            base_url: 本地 MinerU 服务根地址，如 http://127.0.0.1:8000。
            token: 服务端启用 --api-key 时的 Key（可选，默认无鉴权）。
            tier: 解析档位 flash / basic / standard（CPU 建议 basic）。
        """
        self._base = (base_url or "http://127.0.0.1:8000").rstrip("/")
        self._tier = tier or "basic"
        self._session = requests.Session()
        if token:
            self._session.headers.update({"Authorization": f"Bearer {token}"})
        logger.debug(f"MinerU 本地客户端就绪: base={self._base} tier={self._tier}")

    # ── 对外：单文件完整解析 ──────────────────────────────────────

    def parse_pdf(self, pdf_path: Path, work_dir: Path | None = None) -> Path:
        """上传单个 PDF → 等待解析 → 下载产物到工作目录，返回 work_dir。

        Args:
            pdf_path: PDF 文件路径。
            work_dir: 产物输出目录；默认 pdf_path.parent / chunk_out / stem。

        Returns:
            产物目录 Path（内含 ``{stem}.txt`` 与 ``{stem}.middle_json.json``）。

        Raises:
            MinerUError: 任一步失败或解析结果非完成态。
        """
        pdf_path = Path(pdf_path)
        stem = pdf_path.stem
        work_dir = Path(work_dir or pdf_path.parent / "chunk_out" / stem)
        work_dir.mkdir(parents=True, exist_ok=True)

        data = pdf_path.read_bytes()

        # [1/5] 创建上传
        logger.debug(f"[1/5] 创建上传: {pdf_path.name} ({len(data) / 1024:.1f} KB)")
        upload = self._post(f"{self._base}/v1/uploads", {
            "filename": pdf_path.name,
            "bytes": len(data),
            "mime_type": _mime_of(pdf_path.name),
        })
        upload_id = upload.get("id") or upload.get("upload_id")
        if not upload_id:
            raise MinerUError(f"创建上传失败: 响应缺少 id {upload}")

        # [2/5] 传文件字节（同源相对 URL 按基础地址补齐）
        url = upload.get("upload_url") or f"/v1/uploads/{upload_id}/content"
        method = upload.get("upload_method") or "PUT"
        if url.startswith("/"):
            url = self._base + url
        headers = upload.get("upload_headers") or {}
        resp = self._session.request(method, url, data=data, headers=headers, timeout=600)
        if resp.status_code >= 400:
            raise MinerUError(f"上传字节失败 status={resp.status_code} body={resp.text[:200]}")

        # [3/5] 完成上传，取 file_id
        self._post(f"{self._base}/v1/uploads/{upload_id}/complete", {})
        upload_done = self._get(f"{self._base}/v1/uploads/{upload_id}")
        file_id = ((upload_done.get("file") or {}) or {}).get("id")
        if not file_id:
            raise MinerUError(f"上传未完成: status={upload_done.get('status')} {upload_done}")

        # [4/5] 提交单文件解析任务
        logger.debug(f"[4/5] 提交解析任务 tier={self._tier} file_id={file_id}")
        job = self._post(f"{self._base}/v1/parse/jobs", {
            "files": [{"source": {"type": "file_id", "file_id": file_id}}],
            "tier": self._tier,
            "ocr_mode": "auto",
            "output_formats": ["middle_json", "zip"],
        })
        job_id = job.get("job_id") or job.get("id")
        if not job_id:
            raise MinerUError(f"创建任务失败: 响应缺少 job_id {job}")

        # [5/5] 轮询至终态并下载产物
        final = self._poll_job(job_id)
        files = final.get("files") or []
        f0 = files[0] if files else {}
        if f0.get("status") != "completed":
            err = f0.get("error") or final.get("status") or "未知错误"
            raise MinerUError(f"解析失败: {err}")
        outputs = f0.get("output_files") or {}
        for name, suffix in (("middle_json", ".middle_json.json"), ("zip", ".zip")):
            ref = (outputs.get(name) or {})
            fid = ref.get("file_id")
            if fid:
                self._download_output(fid, work_dir / f"{stem}{suffix}")
        logger.debug(f"[5/5] 产物已下载 -> {work_dir}")
        return work_dir

    # ── 轮询 / 下载 ───────────────────────────────────────────────

    def _poll_job(self, job_id: str, interval: float = 3.0, max_wait: float = 3600.0) -> dict:
        """轮询单文件任务至终态（completed / partial / failed / canceled）。"""
        deadline = time.time() + max_wait
        start = time.time()
        while True:
            job = self._get(f"{self._base}/v1/parse/jobs/{job_id}")
            status = job.get("status", "unknown")
            if status in ("completed", "partial", "failed", "canceled"):
                elapsed = time.time() - start
                logger.debug(f"任务终态 status={status} (耗时 {elapsed:.0f}s)")
                return job
            if time.time() > deadline:
                raise MinerUError(f"解析超时 ({max_wait:.0f}s) job={job_id} status={status}")
            time.sleep(interval)

    def _download_output(self, file_id: str, dest: Path) -> None:
        """下载单份产物文件到 dest。"""
        resp = self._session.get(f"{self._base}/v1/files/{file_id}/content", timeout=600)
        if resp.status_code >= 400:
            raise MinerUError(f"下载产物失败 file={file_id} status={resp.status_code}")
        dest.write_bytes(resp.content)

    # ── 底层 HTTP ─────────────────────────────────────────────────

    def _request_with_retry(self, method: str, url: str, **kwargs) -> requests.Response:
        """带指数退避重试的 HTTP 请求（GET/POST）。"""
        last_exc = None
        for attempt in range(4):
            if attempt > 0:
                time.sleep(2 ** (attempt - 1))
            try:
                resp = self._session.request(method, url, timeout=60, **kwargs)
            except requests.RequestException as e:
                last_exc = e
                logger.warning(f"MinerU 请求异常 ({attempt}/3): {e}")
                continue
            if resp.status_code in (502, 503, 504, 429):
                last_exc = MinerUError(f"服务暂不可用 status={resp.status_code}")
                logger.warning(f"MinerU 服务暂不可用 ({attempt}/3): {resp.status_code}")
                continue
            if resp.status_code >= 400:
                return resp
            return resp
        raise MinerUError(f"MinerU API 请求失败 (已重试 3 次): {last_exc}")

    def _post(self, url: str, json_: dict) -> dict:
        resp = self._request_with_retry("POST", url, json=json_)
        return self._check(resp)

    def _get(self, url: str) -> dict:
        resp = self._request_with_retry("GET", url)
        return self._check(resp)

    @staticmethod
    def _check(resp: requests.Response) -> dict:
        """校验响应并按 JSON 返回（本地 V1 无 {code,data} 信封）。"""
        if resp.status_code >= 400:
            try:
                body = resp.text[:300]
            except Exception:
                body = ""
            raise MinerUError(f"API 错误 status={resp.status_code} body={body}")
        try:
            return resp.json()
        except Exception:
            raise MinerUError(
                f"非 JSON 响应 status={resp.status_code} body={resp.text[:300]}"
            )


# ── 内容分块：本地 middle_json（pages.blocks） ─────────────────────

def ocr_image_bytes(data: bytes, filename: str = "image.png") -> str:
    """对单张图片做 OCR（走本地 MinerU），返回识别文本（按块顺序拼接）。

    Args:
        data: 图片字节。
        filename: 原文件名（用于 MinerU 判断图片格式）。

    Returns:
        识别文本；无文字返回空串。
    """
    import tempfile as _tempfile

    if not data:
        return ""
    name = Path(filename or "image.png").name
    with _tempfile.TemporaryDirectory() as td:
        p = Path(td) / name
        p.write_bytes(data)
        client = MinerUClient(
            base_url=conf.mineru_base_url,
            token=conf.mineru_api_key or None,
            tier=conf.mineru_tier or "basic",
        )
        work_dir = client.parse_pdf(p)
        mj = next(work_dir.rglob("*.middle_json.json"), None)
        if mj is None:
            return ""
        content = json.loads(mj.read_text(encoding="utf-8"))
        lines: list[str] = []
        for page in content.get("pages") or []:
            for block in page.get("blocks") or []:
                txt = _runs_to_text(block.get("content") or "").strip()
                if txt:
                    lines.append(txt)
        return "\n".join(lines)


# ── 分块常量 ──


_SKIP_BLOCK_TYPES = frozenset({"header", "footer", "page_number", "page_footnote"})


def _runs_to_text(content) -> str:
    """把 block.content 递归拼成纯文本。

    兼容多种形态：字符串；text run 列表；嵌套块（如 PPT 的 ``type=list`` 子块，
    其 ``content`` 可能再是一层 dict/list，逐层摊平取 text）。
    """
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        return _runs_to_text(content.get("content"))
    if isinstance(content, (list, tuple)):
        parts = []
        for seg in content:
            if isinstance(seg, dict):
                parts.append(_runs_to_text(seg.get("content")))
            elif isinstance(seg, (str, int, float)):
                parts.append(str(seg))
        return "".join(parts)
    return ""


def _block_text(block: dict) -> str:
    """提取 block 文本（table/chart 里取 caption，普通块取 run 文本）。"""
    content = block.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        # table/chart 的子块：caption 或 text 段
        for sub in content:
            if not isinstance(sub, dict):
                continue
            sub_type = sub.get("type", "")
            if sub_type.endswith("_caption"):
                return _runs_to_text(sub.get("content"))
            if sub_type == "text":
                txt = _runs_to_text(sub.get("content"))
                if txt:
                    return txt
            if isinstance(sub.get("content"), list):
                txt = _runs_to_text(sub.get("content"))
                if txt:
                    return txt
    return ""


def _block_table_html(block: dict) -> str:
    """从 table block 提取 table_body 的 HTML。"""
    for sub in block.get("content") or []:
        if isinstance(sub, dict) and str(sub.get("type", "")).endswith("_body"):
            html = sub.get("content") or ""
            if "<table" in html:
                return html
    return ""


def chunk_pages(pages: list, doc_meta: dict, image_paths: list | None = None,
                with_blocks: bool = False) -> list[dict] | tuple[list[dict], dict]:
    """将本地 middle_json 的 pages[].blocks 转为标准分块列表。

    字段与向量库元数据对齐：content / chunk_type / section_path
    / page / caption / footnote / table_body。

    Args:
        pages: middle_json 的 pages 列表。
        doc_meta: 文档元数据。
        image_paths: 按文档顺序抽取出的图片引用列表（``images/img_0001.png`` 等）；
            image/chart 块按序回填 ``img_path``。
        with_blocks: 为 True 时额外返回块映射 ``{(page, block_idx): chunk}``，
            供「MD 切块可视化」逐页标记使用。

    Returns:
        ``with_blocks=False`` 返回分块列表；为 True 返回 ``(chunks, block_map)``。
    """
    chunks: list[dict] = []
    block_map: dict[tuple[int, int], dict] = {}
    img_paths = list(image_paths or [])
    img_idx = 0
    for page in pages or []:
        page_no = (page.get("page_idx") or 0) + 1
        for bidx, block in enumerate(page.get("blocks") or []):
            typ = str(block.get("type", "")).lower()
            if typ in _SKIP_BLOCK_TYPES:
                continue

            if typ in ("table",):
                body_html = _block_table_html(block)
                caption = _block_text(block)
                body_md = _table_html_to_md(body_html) if body_html else ""
                if not caption and not body_md:
                    continue
                c = {
                    "content": _normalize_text(caption or body_md[:80]),
                    "chunk_type": "table",
                    "section_path": [],
                    "page": page_no,
                    "caption": caption,
                    "footnote": "",
                    "table_body": body_md,
                    "img_path": "",
                }
                chunks.append(c)
                block_map[(page_no, bidx)] = c
            elif typ in ("chart", "image"):
                # 每个 image/chart 块对应一张抽取出的图，按序消费；标题仅作 metadata，不影响成块
                img_path = img_paths[img_idx] if img_idx < len(img_paths) else ""
                img_idx += 1
                caption = _block_text(block)
                c = {
                    "content": _normalize_text(caption) if caption else "[图]",
                    "chunk_type": "chart" if typ == "chart" else "image",
                    "section_path": [],
                    "page": page_no,
                    "caption": caption,
                    "footnote": "",
                    "table_body": "",
                    "img_path": img_path,
                }
                chunks.append(c)
                block_map[(page_no, bidx)] = c
            else:  # text / paragraph_title / doc_title / ref_text / equation ...
                text = _runs_to_text(block.get("content"))
                if isinstance(block.get("content"), str) and not text:
                    text = block.get("content") or ""
                if not text:
                    continue
                c = {
                    "content": text,
                    "chunk_type": "text",
                    "section_path": [],
                    "page": page_no,
                }
                chunks.append(c)
                block_map[(page_no, bidx)] = c

    logger.debug(f"MinerU pages.blocks: 解析出 {len(chunks)} 个分块")
    if with_blocks:
        return chunks, block_map
    return chunks


# ── 文本处理工具 ──────────────────────────────────────────────────


def _normalize_text(text: str) -> str:
    """规范表格/图表中的标点为中文符号，压缩空白。"""
    if not text:
        return ""
    text = text.replace(",", "，")
    text = text.replace(":", "：")
    text = text.replace(";", "；")
    text = text.replace("!", "！")
    text = text.replace("?", "？")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _table_html_to_md(html: str) -> str:
    """将 HTML 表格转为 Markdown 表格格式。"""
    if "<table" not in html:
        return re.sub(r"<[^>]+>", "", html).strip()

    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.DOTALL)
    if not rows:
        return re.sub(r"<[^>]+>", "", html).strip()

    md_rows = []
    for ri, row in enumerate(rows):
        cells = re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", row, re.DOTALL)
        md_cells = [re.sub(r"<[^>]+>", "", c).strip() for c in cells]
        md_rows.append("| " + " | ".join(md_cells) + " |")
        if ri == 0 and re.search(r"<th", row, re.IGNORECASE):
            md_rows.append("| " + " | ".join(["---"] * len(md_cells)) + " |")
    return "\n".join(md_rows)


# ── 正文子块：细粒度切分（按段落 → 句子边界到上限） ──

_TEXT_SUB_MAX = 300  # 单个子块最大字符数
_SENT_BOUNDARY_RE = re.compile(r"([^。！？；!?;]*[。！？；!?;]?)")


def _split_text_subchunks(text: str) -> list[str]:
    """把正文块切成细粒度子块（独立入库，独立向量）。

    先按空行/换行切成段落；段落仍超 ``_TEXT_SUB_MAX`` 时按句子边界切开。
    """
    text = (text or "").strip()
    if not text:
        return []
    paras = [p.strip() for p in text.split("\n") if p.strip()]
    out: list[str] = []
    for para in paras:
        if len(para) <= _TEXT_SUB_MAX:
            out.append(para)
            continue
        # 按句子边界切到 ≤ 上限
        buf = ""
        for seg in _SENT_BOUNDARY_RE.findall(para):
            seg = (seg or "").strip()
            if not seg:
                continue
            if len(buf) + len(seg) <= _TEXT_SUB_MAX:
                buf += seg
            else:
                if buf:
                    out.append(buf)
                buf = seg
        if buf:
            out.append(buf)
    return [s.strip() for s in out if s.strip()]


# ── MinerU 文档加载器入口 ──────────────────────────────────────


class MinerULoader:
    """MinerU 本地解析器入口。需要配置 mineru_base_url（本地服务）。"""

    def __init__(self, file_path: str) -> None:
        """初始化。"""
        self.file_path = file_path

    def lazy_load(self) -> Iterator[Document]:
        """惰性加载 PDF：单文件解析 → 分块 → 逐个 yield Document。"""
        from core.models import Document
        path = Path(self.file_path)
        client = MinerUClient(
            base_url=conf.mineru_base_url,
            token=conf.mineru_api_key or None,
            tier=conf.mineru_tier or "basic",
        )
        work_dir = path.parent / "chunk_out" / path.stem
        out_dir = client.parse_pdf(path, work_dir=work_dir)

        doc_meta = {"doc_id": path.stem, "doc_title": path.stem}
        chunks: list[dict] = []

        mid_candidates = [p for p in out_dir.rglob("*.middle_json.json")]
        if mid_candidates:
            content = json.loads(mid_candidates[0].read_text(encoding="utf-8"))
            # 先按块顺序把 middle_json 的图解码落盘（删 base64 前）；PDF 无 base64 时从 zip 的 images/ 取
            image_paths = _write_images_from_json(
                content.get("pages") or [], out_dir,
                zip_path=out_dir / f"{path.stem}.zip",
            )
            _strip_json_base64(out_dir, image_paths)
            # 用 middle_json 渲染纯文本供全文阅读/检索，MinIO 不再保留带内联编码的 md
            try:
                (out_dir / f"{path.stem}.txt").write_text(
                    _render_document_text(content.get("pages") or [], path.stem),
                    encoding="utf-8",
                )
            except OSError:
                pass
            # 清理中转产物（md / 完整结果 zip），不随 chunk_out 上传进 MinIO
            for pat in ("*.md", "*.zip"):
                for f in list(Path(out_dir).rglob(pat)):
                    try:
                        f.unlink()
                    except OSError:
                        pass
            chunks = chunk_pages(content.get("pages") or [], doc_meta, image_paths=image_paths)

        if not chunks:
            raise RuntimeError(f"MinerU 解析结果为空: {path.name}")

        logger.debug(f"MinerU 解析完成: {path.name} -> {len(chunks)} 个 chunks")
        chunk_root = Path(self.file_path).parent / "chunk_out" / path.stem
        for ch in chunks:
            ctype = str(ch.get("chunk_type", "") or "").strip()

            # 表格不录入向量库（全文在 txt 中仍可阅读）
            if ctype == "table":
                continue

            # 图/表：整图向量；标题(caption)进 metadata，text 留空（由 add_documents 处理）
            if ctype in ("image", "chart"):
                meta: dict = {
                    "source": self.file_path,
                    "pre_chunked": True,
                    "chunk_type": ctype,
                    "section_path": ch.get("section_path", []),
                    "page": ch.get("page"),
                    "caption": ch.get("caption", ""),
                    "footnote": ch.get("footnote", ""),
                    "img_path": ch.get("img_path", ""),
                    "table_body": "",
                }
                if meta["img_path"]:
                    img_file = chunk_root / meta["img_path"]
                    try:
                        # svg 等无法被 PIL/CLIP 解码，不参与图向量入库
                        if img_file.is_file() and not str(meta["img_path"]).lower().endswith(".svg"):
                            meta["img_data"] = img_file.read_bytes()
                    except OSError:
                        pass
                yield Document(page_content=meta["caption"], metadata=meta)
                continue

            # 正文：切成子块做细粒度（每子块独立 Document，独立入库）
            parent_text = str(ch.get("content", "") or "").strip()
            parent_id = ""
            if parent_text:
                import hashlib as _hl
                parent_id = _hl.md5(parent_text.encode("utf-8")).hexdigest()
            for sub in _split_text_subchunks(parent_text):
                yield Document(
                    page_content=sub,
                    metadata={
                        "source": self.file_path,
                        "pre_chunked": True,
                        "chunk_type": "text",
                        "section_path": ch.get("section_path", []),
                        "page": ch.get("page"),
                        "caption": "",
                        "footnote": ch.get("footnote", ""),
                        "img_path": "",
                        "table_body": "",
                        "parent_id": parent_id if parent_text != sub else "",
                        "parent_text": parent_text if parent_text != sub else "",
                    },
                )

    def load(self) -> list:
        """立即加载文档（PDF / 图片 / Office），返回所有 Document 列表。"""
        return list(self.lazy_load())