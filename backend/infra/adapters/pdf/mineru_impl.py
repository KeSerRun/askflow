# ── MinerU PDF 解析 ──────────────────────────────────────────────
"""MinerU PDF 解析：API 客户端 → 内容分块 → PDF 加载器。

实现与 MinerU 精准解析 API v4 的对接，涵盖上传、轮询、下载解压
以及 content_list 标准化分块的全流程。
"""

from __future__ import annotations

import json
import re
import time
import uuid
from io import BytesIO
from pathlib import Path
from typing import Iterator, TYPE_CHECKING

import requests

from config import conf
from infra.logger import logger

if TYPE_CHECKING:
    from core.models import Document


# ── 异常定义 ──────────────────────────────────────────────────────


class MinerUError(Exception):
    """MinerU API 调用异常。"""
    pass


class PdfParseError(Exception):
    """PDF 解析失败（解析器统一抛出的异常）。"""
    pass


# ── API 客户端 ────────────────────────────────────────────────────


class MinerUClient:
    """MinerU PDF 解析 API 客户端（对接精准解析 API v4）。

    解析流程：
      1. POST {base}/file-urls/batch → 获取签名上传 URL + batch_id
      2. PUT 文件到签名 URL → 系统自动开始解析
      3. GET {base}/extract-results/batch/{batch_id} → 轮询至全部完成
      4. 下载 ZIP → 解压到输出目录

    Attributes:
        token: API 认证令牌。
        _base: API 基础地址。
        _session: 复用的 requests Session。
    """

    def __init__(self, token: str):
        """初始化 MinerU 客户端。

        Args:
            token: API 令牌（必填，由调用方显式提供）。

        Raises:
            MinerUError: 未提供 API Token 时抛出。
        """
        self.token = token
        if not self.token:
            raise MinerUError(
                "缺少 API Token。请在 .env 中配置 MINERU_API_KEY "
                "(申请地址: https://mineru.net/apiManage)"
            )
        self._base = conf.mineru_base_url.rstrip("/")
        self._session = requests.Session()
        self._session.headers.update({"Authorization": f"Bearer {self.token}"})
        logger.debug(f"MinerU 客户端就绪: token={self.token[:12]}...")

    # ── 完整解析流程 ──────────────────────────────────────────────

    def parse_pdf(self, pdf_path: Path, work_dir: Path | None = None,
                  model_version: str = "vlm", language: str = "ch") -> Path:
        """上传 PDF → 等待解析 → 下载解压，返回输出目录。

        Args:
            pdf_path: PDF 文件路径。
            work_dir: 输出工作目录；默认使用 pdf_path 同级 chunk_out/<stem>。
            model_version: MinerU 模型版本（如 "vlm"）。
            language: 解析语言（如 "ch"）。

        Returns:
            解压后的输出目录 Path。
        """
        pdf_path = Path(pdf_path)
        work_dir = Path(work_dir or pdf_path.parent / "chunk_out" / pdf_path.stem)
        work_dir.mkdir(parents=True, exist_ok=True)

        logger.debug(f"[1/4] 申请上传 URL: {pdf_path.name}")
        batch_id, put_url = self._request_upload_url(pdf_path.name, model_version, language)
        logger.debug(f"      batch_id={batch_id}")

        logger.debug(f"[2/4] 上传 PDF ({pdf_path.stat().st_size / 1024:.1f} KB)")
        self._upload_file(put_url, pdf_path)

        logger.debug(f"[3/4] 等待解析完成")
        results = self._poll_batch(batch_id)
        item = results[0]
        if item.get("state") != "done":
            raise MinerUError(f"解析失败: {item.get('err_msg') or item}")

        zip_url = item["full_zip_url"]
        logger.debug(f"[4/4] 下载并解压: {zip_url}")
        out = self._download_zip(zip_url, work_dir)
        logger.debug(f"      -> {out}")
        return out

    # ── 内部 HTTP 流程 ────────────────────────────────────────────

    def _request_upload_url(self, file_name: str,
                            model_version: str = "vlm",
                            language: str = "ch") -> tuple[str, str]:
        """获取签名上传 URL 和 batch_id。

        Args:
            file_name: 文件名。
            model_version: MinerU 模型版本。
            language: 解析语言。

        Returns:
            (batch_id, presigned_url) 元组。
        """
        data_id = str(uuid.uuid4())
        payload = {
            "files": [{"name": file_name, "data_id": data_id}],
            "model_version": model_version,
            "is_ocr": True,
            "enable_formula": True,
            "enable_table": True,
            "language": language,
        }
        body = self._post(f"{self._base}/file-urls/batch", payload)
        return body["batch_id"], body["file_urls"][0]

    def _upload_file(self, presigned_url: str, file_path: Path):
        """PUT 文件到签名 URL。

        Args:
            presigned_url: 预签名上传地址。
            file_path: 本地文件路径。

        Raises:
            MinerUError: 上传失败时抛出。
        """
        with open(file_path, "rb") as f:
            r = requests.put(presigned_url, data=f, timeout=300)
        if r.status_code not in (200, 204):
            raise MinerUError(f"上传失败 status={r.status_code} body={r.text[:200]}")

    def _poll_batch(self, batch_id: str, interval: float = 5.0,
                    max_wait: float = 1200.0) -> list[dict]:
        """轮询解析结果，返回 extract_result 列表。

        Args:
            batch_id: 批次 ID。
            interval: 轮询间隔秒数。
            max_wait: 最大等待秒数。

        Returns:
            extract_result 列表，每项为包含解析状态和结果的 dict。

        Raises:
            MinerUError: 超时或 API 返回异常时抛出。
        """
        deadline = time.time() + max_wait
        start = time.time()
        url = f"{self._base}/extract-results/batch/{batch_id}"
        last_heartbeat = -1

        while True:
            body = self._get(url)

            if not isinstance(body, dict):
                raise MinerUError(
                    f"API 返回了意外的 data 类型: {type(body).__name__}, "
                    f"期望 dict, 内容: {str(body)[:200]}"
                )

            raw = body.get("extract_result")
            results = raw if isinstance(raw, list) else []

            if results:
                states = {
                    it.get("data_id") or it.get("file_name", "?"):
                        it.get("state", "unknown")
                    for it in results
                }
                logger.debug(f"轮询状态: {states}")
            else:
                elapsed = time.time() - start
                logger.debug(f"extract_result 为空 (已等待 {elapsed:.0f}s), 继续等待...")

            done_count = sum(
                1 for it in results
                if it.get("state") in ("done", "failed")
            )
            if results and done_count == len(results):
                return results

            elapsed = time.time() - start
            if time.time() > deadline:
                parts = [f"轮询超时 ({max_wait:.0f}s) batch={batch_id}"]
                if results:
                    parts.append(f"{done_count}/{len(results)} done")
                    states = {
                        it.get("data_id") or it.get("file_name", "?"):
                            it.get("state", "unknown")
                        for it in results
                    }
                    parts.append(f"states={states}")
                raise MinerUError(" ".join(parts))

            heartbeat = int(elapsed) // 30
            if heartbeat > last_heartbeat:
                last_heartbeat = heartbeat
                status = (
                    f"{done_count}/{len(results)} 完成"
                    if results else "等待 API 返回结果"
                )
                logger.debug(f"[3/4] 仍在等待 (已等待 {elapsed:.0f}s, {status})...")

            time.sleep(interval)

    def _download_zip(self, zip_url: str, out_dir: Path) -> Path:
        """下载并解压 ZIP。

        Args:
            zip_url: ZIP 文件下载地址。
            out_dir: 解压目标目录。

        Returns:
            解压后的目录路径。
        """
        r = requests.get(zip_url, timeout=120)
        r.raise_for_status()
        import zipfile
        with zipfile.ZipFile(BytesIO(r.content)) as zf:
            zf.extractall(out_dir)
        return out_dir

    # ── 底层 HTTP 工具 ────────────────────────────────────────────

    def _request_with_retry(self, method: str, url: str, **kwargs) -> requests.Response:
        """带指数退避重试的 HTTP 请求。

        最多重试 3 次，间隔 1s → 2s → 4s，仅对可重试的异常进行重试。

        Args:
            method: "GET" 或 "POST"。
            url: 请求 URL。
            **kwargs: 传给 requests.Session.request 的参数。

        Returns:
            requests.Response 对象。

        Raises:
            MinerUError: 所有重试耗尽后仍失败时抛出。
        """
        import time as _time

        last_exc = None
        for attempt in range(4):  # 首次 + 3 次重试
            if attempt > 0:
                wait = 2 ** (attempt - 1)  # 1, 2, 4 秒
                logger.debug(f"MinerU API 重试 ({attempt}/3), 等待 {wait}s...")
                _time.sleep(wait)
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
            # 4xx（除 429 外）不重试，直接抛
            if resp.status_code >= 400:
                return self._check(resp)
            return resp

        raise MinerUError(f"MinerU API 请求失败 (已重试 3 次): {last_exc}")

    def _post(self, url: str, payload: dict) -> dict:
        resp = self._request_with_retry("POST", url, json=payload)
        return self._check(resp)

    def _get(self, url: str) -> dict:
        resp = self._request_with_retry("GET", url)
        return self._check(resp)

    @staticmethod
    def _check(resp: requests.Response) -> dict:
        """检查 API 响应并提取 data 字段。

        Args:
            resp: requests.Response 对象。

        Returns:
            API 响应中的 data 字段。

        Raises:
            MinerUError: 响应异常时抛出。
        """
        try:
            body = resp.json()
        except Exception:
            raise MinerUError(
                f"非 JSON 响应 status={resp.status_code} body={resp.text[:300]}"
            )
        if body.get("success") is False:
            err_code = body.get("msgCode") or "?"
            err_msg = body.get("msg") or "未知错误"
            trace = body.get("traceId") or body.get("trace_id") or ""
            raise MinerUError(
                f"API 错误 code={err_code} msg={err_msg} trace={trace}"
            )
        if body.get("code") != 0:
            raise MinerUError(
                f"API 错误 code={body.get('code')} msg={body.get('msg')} "
                f"trace={body.get('trace_id')}"
            )
        if "data" not in body:
            raise MinerUError(
                f"API 响应缺少 data 字段, body keys={list(body.keys())[:10]}, "
                f"msg={body.get('msg', '')}"
            )
        return body["data"]


# ── 内容分块工具 ──────────────────────────────────────────────────


def chunk_content_list(content_list: list, doc_meta: dict) -> list[dict]:
    """将 MinerU 的 content_list 转为标准化的分块列表。

    MinerU 字段说明：
      - type: text / table / chart / header / footer / image
      - page_idx: 页码（从 0 开始）
      - text / table_body / content: 正文内容
      - img_path: 图片路径
      - table_caption / chart_caption / table_footnote / chart_footnote: 标题/注释
      - bbox: 坐标 [x0, y0, x1, y1]

    Args:
        content_list: MinerU 返回的 content_list 或包含该字段的 dict。
        doc_meta: 文档元数据（当前未使用，预留扩展）。

    Returns:
        标准化分块字典列表，每项包含 content / chunk_type / section_path / page 等。
    """
    if isinstance(content_list, dict):
        content_list = content_list.get("content_list", content_list)
    if not isinstance(content_list, list):
        return []
    chunks = []

    sorted_items = sorted(
        content_list,
        key=lambda x: (x.get("page_idx", 0), x.get("bbox", [0, 0, 0, 0])[1]),
    )

    for item in sorted_items:
        typ = item.get("type", "")
        page = (item.get("page_idx") or 0) + 1

        if typ in ("header", "footer"):
            continue

        if typ == "text":
            text = _extract_text(item)
            if not text:
                continue
            chunks.append({
                "content": text,
                "chunk_type": "text",
                "section_path": _extract_section(item.get("title", "")),
                "page": page,
            })

        elif typ in ("table", "chart"):
            img_path = item.get("img_path", "")
            caption = "".join(item.get(f"{typ}_caption", []) or [])
            footnote = "".join(item.get(f"{typ}_footnote", []) or [])
            body_html = item.get("table_body") or item.get("content") or ""
            body_text = _table_html_to_md(body_html) if body_html else ""
            if not caption and not body_text:
                continue
            chunks.append({
                "content": _normalize_text(caption or (body_text[:80] + "..." if len(body_text) > 80 else body_text)),
                "chunk_type": typ,
                "section_path": _extract_section(item.get("title", "")),
                "page": page,
                "img_path": img_path,
                "caption": caption,
                "footnote": footnote,
                "table_body": body_text if typ == "table" else "",
            })

    logger.debug(f"MinerU content_list: {len(content_list)} items -> {len(chunks)} chunks")
    return chunks


# ── 文本处理工具 ──────────────────────────────────────────────────


def _extract_text(item: dict) -> str:
    """从 item 中提取文本内容。

    Args:
        item: MinerU 内容项字典。

    Returns:
        拼接后的文本字符串。
    """
    texts = item.get("text", "")
    if isinstance(texts, list):
        return "".join(texts)
    return str(texts) if texts else ""


def _extract_section(title: str) -> list:
    """将标题解析为章节路径列表。

    Args:
        title: 以 ">" 分隔的标题字符串。

    Returns:
        章节名称列表。
    """
    if not title:
        return []
    return [s.strip() for s in title.split(">") if s.strip()]


def _normalize_text(text: str) -> str:
    """规范表格/图表中的标点为中文符号，压缩空白。

    Args:
        text: 原始文本。

    Returns:
        规范化后的文本。
    """
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
    """将 HTML 表格转为 Markdown 表格格式。

    Args:
        html: HTML 表格字符串。

    Returns:
        Markdown 表格字符串。
    """
    import re
    if "<table" not in html:
        return re.sub(r"<[^>]+>", "", html).strip()

    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.DOTALL)
    if not rows:
        return re.sub(r"<[^>]+>", "", html).strip()

    md_rows = []
    for ri, row in enumerate(rows):
        cells = re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", row, re.DOTALL)
        md_cells = []
        for c in cells:
            clean = re.sub(r"<[^>]+>", "", c).strip()
            clean = re.sub(r"\s+", " ", clean)
            md_cells.append(clean)
        md_rows.append("| " + " | ".join(md_cells) + " |")

        if ri == 0 and re.search(r"<th", row, re.IGNORECASE):
            md_rows.append("| " + " | ".join(["---"] * len(md_cells)) + " |")

    return "\n".join(md_rows)


# ── PDF 加载器入口 ────────────────────────────────────────────────


class MinerUPDFLoader:
    """MinerU PDF 解析器入口。需要配置 mineru_api_key。

    Attributes:
        file_path: PDF 文件路径。
    """

    def __init__(self, file_path: str) -> None:
        """初始化 MinerU PDF 加载器。

        Args:
            file_path: PDF 文件路径。
        """
        self.file_path = file_path

    def lazy_load(self) -> Iterator[Document]:
        """惰性加载 PDF：解析 → 分块 → 逐个 yield Document。

        Yields:
            每个分块对应一个 Document 实例。

        Raises:
            RuntimeError: 解析结果为空或缺少 content_list.json 时抛出。
        """
        from core.models import Document
        path = Path(self.file_path)
        client = MinerUClient(token=conf.mineru_api_key or None)
        work_dir = path.parent / "chunk_out" / path.stem
        out_dir = client.parse_pdf(
            path, work_dir=work_dir,
            model_version=conf.mineru_model_version,
            language=conf.mineru_language,
        )
        candidates = [p for p in out_dir.rglob("*content_list.json") if "v2" not in p.name]
        if not candidates:
            raise RuntimeError(f"MinerU 输出未找到 content_list.json: {path.name}")
        content = json.loads(candidates[0].read_text(encoding="utf-8"))
        if isinstance(content, dict):
            content = content.get("content_list", content)
        doc_meta = {"doc_id": path.stem, "doc_title": path.stem}
        chunks = chunk_content_list(content, doc_meta)
        if not chunks:
            raise RuntimeError(f"MinerU 切块结果为空: {path.name}")
        logger.debug(f"MinerU 解析完成: {path.name} -> {len(chunks)} 个 chunks")
        for ch in chunks:
            content_text = ch.get("content", "")
            if not content_text:
                continue
            yield Document(
                page_content=content_text,
                metadata={
                    "source": self.file_path,
                    "pre_chunked": True,
                    "chunk_type": ch.get("chunk_type", ""),
                    "section_path": ch.get("section_path", []),
                    "page": ch.get("page"),
                    "caption": ch.get("caption", ""),
                    "footnote": ch.get("footnote", ""),
                    "img_path": ch.get("img_path", ""),
                    "table_body": ch.get("table_body", ""),
                },
            )

    def load(self) -> list:
        """立即加载 PDF，返回所有 Document 列表。

        Returns:
            Document 实例列表。
        """
        return list(self.lazy_load())