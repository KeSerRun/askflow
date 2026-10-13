"""modules.database.service —— 管理后台「向量库 / 文档」用例。

供管理后台查看与维护向量库：
  - 统计概览（切块/向量/分区/来源/类型/嵌入信息）；
  - 切块浏览（分页 + 过滤）；
  - 系统级文档（``__system__`` 分区）的列出 / 上传（后台任务）/ 状态；
  - 删除 / 批量删除（任意分区的向量 + 原文件 + chunk 产物）。

依赖组合根注入的 ``vector_store`` / ``document_service`` / ``object_store``。
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

from agent.tools import SYSTEM_PARTITION
from core.app_errors import InvalidInput, NotFound
from core.models import Document
from core.pagination import paginate
from infra.util.logger import logger
from modules.document.backend import FileStore


class DatabaseService:
    """管理后台的数据（向量库/文档）运维用例。"""

    def __init__(self, vector_store: object, document_service: object, *,
                 object_store: object = None, parent_store: object = None, workers: int = 3):
        """初始化。

        Args:
            vector_store: 向量库适配器。
            document_service: 文档用例（复用其 purge / 保存等能力）。
            object_store: 对象存储适配器（MinIO）。
            parent_store: 父块内容存储（ChunkParentStore；None 则父块功能不可用）。
            workers: 系统文档后台处理的并发上限。
        """
        self._vector = vector_store
        self._docs = document_service
        self._files = FileStore(object_store)
        self._parents = parent_store
        self._workers = max(1, int(workers or 1))
        self._tasks: dict[str, dict] = {}
        self._lock = threading.Lock()

    # ── 统计概览 ──

    def stats(self) -> dict:
        """向量库统计：切块/向量总数、按来源分布、类型、嵌入信息（默认只使用 __system__ 分区）。"""
        vs = self._vector
        if vs is None:
            return {"available": False, "message": "向量存储未初始化"}

        metadata = vs.metadata or []
        vectors = getattr(vs, "dense_vectors", []) or []

        by_source: dict = {}
        for m in metadata:
            s = m.get("source", "unknown")
            b = by_source.setdefault(s, {"chunks": 0})
            b["chunks"] += 1

        return {
            "available": True,
            "embedding_model": getattr(vs, "embedding_model", None),
            "embedding_dimension": getattr(vs, "dimension", None),
            "total_chunks": len(metadata),
            "total_vectors": len(vectors),
            "sources_count": len(by_source),
            "chunk_types": sorted({m.get("chunk_type", "") for m in metadata if m.get("chunk_type")}),
            "by_source": {
                s: {"chunks": v["chunks"]}
                for s, v in by_source.items()
            },
        }

    # ── 切块浏览 ──

    def chunks(self, *, page: int = 1, page_size: int = 20,
               source: str | None = None,
               chunk_type: str | None = None, query_text: str | None = None) -> dict:
        """切块详情列表（分页 + 可选过滤）。"""
        vs = self._vector
        metadata = (vs.metadata if vs else []) or []

        filtered = metadata
        if source:
            filtered = [m for m in filtered if m.get("source") == source]
        if chunk_type:
            filtered = [m for m in filtered if m.get("chunk_type") == chunk_type]
        if query_text:
            q = query_text.lower()
            filtered = [m for m in filtered if q in (m.get("text") or "").lower()]

        return paginate(
            (self._simplify_chunk(m) for m in filtered),
            page, page_size, key="items",
        )

    @staticmethod
    def _simplify_chunk(m: dict) -> dict:
        return {
            "id": m.get("id", ""),
            "text": (m.get("text") or "")[:200],
            "text_full": m.get("text", ""),
            "parent_id": m.get("parent_id", ""),
            "source": m.get("source", ""),
            "chunk_type": m.get("chunk_type", ""),
            "page": m.get("page"),
            "img_path": m.get("img_path", ""),
            "caption": m.get("caption", "") or "",
        }

    def chunk_parent_text(self, parent_id: str) -> dict:
        """按父块 id 返回父块（未切分整段）全文；不存在抛 NotFound。"""
        if self._parents is None:
            raise NotFound("父块存储不可用")
        text = self._parents.get_parent(parent_id)
        if not text:
            raise NotFound("父块不存在")
        return {"parent_id": parent_id, "text": text}

    # ── 系统级文档 ──

    def list_system_docs(self, *, page: int = 1, page_size: int = 0) -> dict:
        """列出已入库的系统文档：向量库中 ``__system__`` 分区的来源及其切块数（分页）。

        以**向量库**为准——只有真正切块入库的文档才会出现（chunks>0）；
        MinIO 原始文件清单（含未入库文件）见 :meth:`list_system_raw_files`。
        """
        vs = self._vector
        chunk_counts: dict[str, int] = {}
        for m in (vs.metadata if vs else []) or []:
            if m.get("partition") != SYSTEM_PARTITION:
                continue
            src = m.get("source")
            if src:
                chunk_counts[src] = chunk_counts.get(src, 0) + 1
        items = [
            {"name": s, "chunks": chunk_counts[s]}
            for s in sorted(chunk_counts)
        ]
        return paginate(items, page, page_size, key="documents")

    def list_system_raw_files(self, *, page: int = 1, page_size: int = 0) -> dict:
        """列出上传到 MinIO ``uploads/__system__/`` 的原始文件（分页）。

        以**对象存储实际文件**为准（含未成功向量化的文件——chunks=0），
        是否已入库（``imported`` / ``chunks``）从向量库统计。
        """
        vs = self._vector
        prefix = f"uploads/{SYSTEM_PARTITION}/"
        names: set[str] = set()
        for obj in self._files.list_all(prefix):
            name = obj["name"]
            if "/chunk_out/" in name or not name.startswith(prefix):
                continue
            fname = name[len(prefix):]
            if fname:
                names.add(fname)
        chunk_counts: dict[str, int] = {}
        for m in (vs.metadata if vs else []) or []:
            if m.get("partition") != SYSTEM_PARTITION:
                continue
            src = m.get("source")
            if src:
                chunk_counts[src] = chunk_counts.get(src, 0) + 1
        items = [
            {
                "name": s,
                "chunks": chunk_counts.get(s, 0),
                "imported": chunk_counts.get(s, 0) > 0,
            }
            for s in sorted(names)
        ]
        return paginate(items, page, page_size, key="files")

    # ── MD 切块可视化（按页展示文档 md，标记每页内的切块边界） ──

    @staticmethod
    def _segment_text(typ: str, block: dict) -> str:
        """取块的展示文本（与向量化逻辑口径一致）。"""
        from infra.adapters.pdf.mineru_impl import (
            _SKIP_BLOCK_TYPES, _block_table_html, _block_text,
            _runs_to_text, _table_html_to_md,
        )
        if typ in _SKIP_BLOCK_TYPES:
            return _runs_to_text(block.get("content") or "")
        if typ == "table":
            text = _block_text(block)
            if not text:
                html = _block_table_html(block)
                text = _table_html_to_md(html) if html else ""
            return text or "(表格)"
        if typ in ("chart", "image"):
            return _block_text(block) or "(图)"
        return _runs_to_text(block.get("content") or "")

    def md_view(self, source: str) -> dict:
        """按页展示文档 md 并标记切块。

        用与入库相同的 ``chunk_pages`` 重放块分块，再以 ``md5(块文本)`` 对齐向量库
        真实切块（doc_id），从而判断每块是否成块 / 被过滤。

        Returns:
            ``{"available": False, "reason": ...}`` 或
            ``{"available": True, "source", "stem", "total_chunks", "pages": [{page, segments}]}``，
            segment 含 ``marked / chunk_id / chunk_type / text / img_path / reason``。
        """
        if not source:
            raise ValueError("缺少参数 source")
        name = os.path.basename(source)
        stem = Path(name).stem

        vs = self._vector
        if vs is None:
            return {"available": False, "reason": "向量存储未初始化"}

        meta_by_page_id: dict[tuple[int, str], dict] = {}
        for m in (vs.metadata or []):
            if m.get("source") == name and m.get("id"):
                meta_by_page_id[(int(m.get("page") or 0), m["id"])] = m

        mid_key = None
        for obj in self._files.list_all(f"uploads/{SYSTEM_PARTITION}/chunk_out/{stem}"):
            if obj["name"].endswith(".middle_json.json"):
                mid_key = obj["name"]
                break
        if mid_key is None:
            return {"available": False, "reason": "缺少 middle_json 产物，无法按页展示（旧格式或解析失败）"}
        raw = self._files.get_bytes(mid_key)
        if not raw:
            return {"available": False, "reason": "middle_json 产物读取失败"}
        try:
            content = json.loads(raw.decode("utf-8"))
        except Exception:  # noqa: BLE001
            return {"available": False, "reason": "middle_json 解析失败"}
        pages = content.get("pages") or []

        from infra.adapters.pdf.mineru_impl import _SKIP_BLOCK_TYPES, chunk_pages

        # 与入库一致的 image_paths（按对象存储 images/ 下的文件名顺序）
        img_paths = sorted(
            "images/" + obj["name"].split("images/", 1)[1]
            for obj in self._files.list_all(f"uploads/{SYSTEM_PARTITION}/chunk_out/{stem}")
            if "/images/" in obj["name"]
        )
        _chunks, block_map = chunk_pages(pages, {"doc_id": stem}, image_paths=img_paths, with_blocks=True)

        pages_out = []
        for page in pages:
            pno = (page.get("page_idx") or 0) + 1
            segments = []
            for bidx, block in enumerate(page.get("blocks") or []):
                typ = str(block.get("type", "")).lower()
                text = self._segment_text(typ, block)
                chunk = block_map.get((pno, bidx))
                if chunk is None:
                    reason = "页眉/页脚等" if typ in _SKIP_BLOCK_TYPES else "未成块"
                    segments.append({
                        "marked": False, "reason": reason,
                        "chunk_id": "", "chunk_type": typ, "text": text, "img_path": "",
                        "page": pno, "bidx": bidx,
                    })
                    continue
                # 对齐向量库（当前方案）：图块 doc_id=md5(img_path)；文本块 doc_id=md5(块文本)
                ctype = (chunk.get("chunk_type") or "").strip()
                if ctype in ("image", "chart") and chunk.get("img_path"):
                    did = hashlib.md5((chunk["img_path"] or "").encode("utf-8")).hexdigest()
                else:
                    did = hashlib.md5((chunk.get("content") or "").encode("utf-8")).hexdigest()
                page_key = int(chunk.get("page") or 0)
                rec = meta_by_page_id.get((page_key, did))
                if rec is None:
                    if ctype == "table":
                        reason = "表格不录入向量库"
                    elif ctype in ("image", "chart"):
                        reason = "图未向量化（格式不支持）"
                    else:
                        reason = "被过滤（过短 / 停用词）"
                    segments.append({
                        "marked": False, "reason": reason,
                        "chunk_id": "", "chunk_type": typ, "text": text,
                        "img_path": chunk.get("img_path") or "",
                        "page": pno, "bidx": bidx,
                    })
                else:
                    segments.append({
                        "marked": True,
                        "chunk_id": did[:8],
                        "chunk_type": rec.get("chunk_type") or typ,
                        "text": text,
                        "img_path": rec.get("img_path") or "",
                        "page": rec.get("page") or pno,
                        "bidx": bidx,
                    })
            pages_out.append({"page": pno, "segments": segments})

        return {
            "available": True,
            "source": name,
            "stem": stem,
            "paginated": len(pages) > 1,   # 仅 PDF/PPT 等多原始页才有真实页；docx 等连续排版为 False
            "total_chunks": len(meta_by_page_id),
            "pages": pages_out,
        }

    # ── 手动调整：文档视图未嵌入块→入库 / 已嵌入块→移除 ──

    def _view_chunks(self, name: str) -> tuple[list, dict]:
        """读取文档 middle_json，按与入库一致的规则重放分块。

        Returns:
            ``(pages, block_map)``；block_map 键为 ``(page, bidx)``。
        """
        stem = Path(os.path.basename(name)).stem
        mid_key = next(
            (o["name"] for o in self._files.list_all(
                f"uploads/{SYSTEM_PARTITION}/chunk_out/{stem}")
             if o["name"].endswith(".middle_json.json")),
            None,
        )
        if not mid_key:
            raise NotFound(f"缺少 middle_json 产物: {name}")
        raw = self._files.get_bytes(mid_key)
        if not raw:
            raise NotFound("middle_json 产物读取失败")
        try:
            content = json.loads(raw.decode("utf-8"))
        except Exception:  # noqa: BLE001
            raise NotFound("middle_json 解析失败")
        pages = content.get("pages") or []

        from infra.adapters.pdf.mineru_impl import chunk_pages

        img_paths = sorted(
            "images/" + obj["name"].split("images/", 1)[1]
            for obj in self._files.list_all(f"uploads/{SYSTEM_PARTITION}/chunk_out/{stem}")
            if "/images/" in obj["name"]
        )
        _chunks, block_map = chunk_pages(
            pages, {"doc_id": stem}, image_paths=img_paths, with_blocks=True)
        return pages, block_map

    @staticmethod
    def _chunk_doc_id(chunk: dict) -> str:
        """按 md_view 口径计算块的主键 doc_id（图=md5(img_path)；文本=md5(块文本)）。"""
        ctype = str(chunk.get("chunk_type") or "").strip()
        if ctype in ("image", "chart") and chunk.get("img_path"):
            return hashlib.md5((chunk["img_path"] or "").encode("utf-8")).hexdigest()
        return hashlib.md5((chunk.get("content") or "").encode("utf-8")).hexdigest()

    def mdview_embed(self, source: str, page: int, block_idx: int) -> dict:
        """把文档视图中未嵌入的指定块手动嵌入向量库。"""
        pages, block_map = self._view_chunks(source)
        pno, bidx = int(page), int(block_idx)
        chunk = block_map.get((pno, bidx))
        if chunk is None:
            raise NotFound(f"第 {pno} 页第 {bidx} 块不存在")
        ctype = str(chunk.get("chunk_type") or "").strip()
        if ctype == "table":
            raise InvalidInput("表格不录入向量库，无法手动嵌入")
        vs = self._vector
        if vs is None:
            raise NotFound("向量存储未初始化")
        stem = Path(os.path.basename(source)).stem
        meta = {
            "source": os.path.basename(source),
            "pre_chunked": True,
            "chunk_type": ctype,
            "page": pno,
            "caption": chunk.get("caption", ""),
            "footnote": chunk.get("footnote", ""),
            "img_path": chunk.get("img_path", ""),
            "table_body": "",
        }
        if ctype in ("image", "chart"):
            ip = meta["img_path"]
            if not ip:
                raise InvalidInput("该块没有图片文件")
            if ip.lower().endswith(".svg"):
                raise InvalidInput("svg 格式不支持向量化")
            data = self._files.get_bytes(
                f"uploads/{SYSTEM_PARTITION}/chunk_out/{stem}/{ip}")
            if not data:
                raise NotFound(f"图片文件缺失: {ip}")
            meta["img_data"] = data
            doc = Document(page_content=meta["caption"], metadata=meta)
        else:
            text = str(chunk.get("content") or "").strip()
            if not text:
                raise InvalidInput("该块没有文本内容")
            meta["chunk_type"] = "text"
            meta["img_path"] = ""
            doc = Document(page_content=text, metadata=meta)
        vs.add_documents([doc])
        return {"message": "已嵌入向量库", "source": os.path.basename(source),
                "page": pno, "block_idx": bidx, "chunk_type": ctype}

    def mdview_remove(self, source: str, page: int, block_idx: int) -> dict:
        """把文档视图中已嵌入块的向量从库里移除（不动 middle_json/图片）。"""
        pages, block_map = self._view_chunks(source)
        pno, bidx = int(page), int(block_idx)
        chunk = block_map.get((pno, bidx))
        if chunk is None:
            raise NotFound(f"第 {pno} 页第 {bidx} 块不存在")
        did = self._chunk_doc_id(chunk)
        self._vector.delete_by_doc_ids([did])
        return {"message": "已从向量库移除", "doc_id": did,
                "chunk_type": str(chunk.get("chunk_type") or "")}

    def upload_system(self, files_data: list[tuple[str, bytes, str]]) -> dict:
        """上传系统级文档并后台解析入库，立即返回任务 ID。

        Args:
            files_data: ``[(filename, content_bytes, content_type), ...]``。
        """
        if not files_data:
            raise ValueError("未提供文件")

        task_id = "upload_" + uuid.uuid4().hex[:8]
        prepared: list[tuple[str, bytes]] = []
        for raw_name, content, _ct in files_data:
            if not content:
                continue
            name = self._docs.sanitize_filename(raw_name)
            prepared.append((name, content))

        with self._lock:
            self._tasks[task_id] = {
                "id": task_id,
                "filenames": [p[0] for p in prepared],
                "status": "processing" if prepared else "finished",
                "total": len(prepared),
                "success": 0,
                "fail": 0,
                "failures": [],
                "files": {p[0]: "pending" for p in prepared},   # 逐文件状态: pending/processing/success/failed
                "started_at": datetime.now().isoformat(timespec="seconds"),
                "finished_at": None,
            }

        if prepared:
            threading.Thread(target=self._run_upload, args=(task_id, prepared), daemon=True).start()

        return {"task_id": task_id, "message": f"已接收 {len(prepared)} 个文件，后台向量化处理中",
                "files": [p[0] for p in prepared]}

    def _run_upload(self, task_id: str, prepared: list[tuple[str, bytes]]) -> None:
        task = self._tasks[task_id]

        def _one(fname: str, content: bytes) -> None:
            # 覆盖入库：先删同名向量与旧产物，再落盘 + 解析（复用 DocumentService.upload）
            with self._lock:
                task["files"][fname] = "processing"
            try:
                self._docs.upload(SYSTEM_PARTITION, fname, content)
                with self._lock:
                    task["success"] += 1
                    task["files"][fname] = "success"
            except Exception as e:  # noqa: BLE001
                with self._lock:
                    task["fail"] += 1
                    task["failures"].append(fname)
                    task["files"][fname] = "failed"
                logger.error(f"系统文档入库失败 ({fname}): {e}")

        with ThreadPoolExecutor(max_workers=self._workers) as pool:
            futures = {pool.submit(_one, fn, ct): fn for fn, ct in prepared}
            for future in as_completed(futures):
                future.result()
        with self._lock:
            task["status"] = "finished"
            task["finished_at"] = datetime.now().isoformat(timespec="seconds")

    def upload_task(self, task_id: str) -> dict:
        """按任务 ID 返回上传任务详情（含逐文件状态）。

        Raises:
            KeyError: 任务不存在。
        """
        with self._lock:
            task = self._tasks.get(task_id)
        if task is None:
            raise KeyError(task_id)
        return {**task, "files": dict(task.get("files") or {})}

    def delete(self, source: str) -> None:
        """删除指定文档（向量 + 原文件 + chunk 产物）。"""
        if not source:
            raise ValueError("缺少参数 source")
        self._vector.delete_by_sources([source])
        self._docs.purge(SYSTEM_PARTITION, [source])

    def delete_raw_file(self, source: str) -> dict:
        """仅删除 ``uploads/__system__/`` 下的原始文件；向量与切块产物保留。"""
        if not source:
            raise ValueError("缺少参数 source")
        name = os.path.basename(source)
        self._files.delete(f"uploads/{SYSTEM_PARTITION}/{name}")
        return {"message": f"已删除原始文件 {name}（向量/切块保留）"}
