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
import re
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

from .entity import KnowledgeBase


class DatabaseService:
    """管理后台的数据（向量库/文档）运维用例。"""

    def __init__(self, vector_store: object, document_service: object, *,
                 object_store: object = None, parent_store: object = None,
                 repo: object = None, workers: int = 3):
        """初始化。

        Args:
            vector_store: 向量库适配器。
            document_service: 文档用例（复用其 purge / 保存等能力）。
            object_store: 对象存储适配器（MinIO）。
            parent_store: 父块内容存储（ChunkParentStore；None 则父块功能不可用）。
            repo: 通用仓储（``knowledge_bases`` 表；None 则知识库目录不可持久化）。
            workers: 系统文档后台处理的并发上限。
        """
        self._vector = vector_store
        self._docs = document_service
        self._files = FileStore(object_store)
        self._parents = parent_store
        self._repo = repo
        self._workers = max(1, int(workers or 1))
        self._tasks: dict[str, dict] = {}
        self._lock = threading.Lock()

    # ── 统计概览 ──

    def stats(self) -> dict:
        """向量库统计：切块/向量总数、按来源分布、类型、嵌入信息（默认只使用 __system__ 分区）。"""
        vs = self._vector
        if vs is None or not getattr(vs, "is_available", lambda: True)():
            return {"available": False, "message": "向量存储未初始化或连接失败"}

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

    # ── 知识库管理（分区） ──

    _KB_COLLECTION = "knowledge_bases"
    _KB_NAME_MAX = 64

    @classmethod
    def _normalize_kb_name(cls, raw: str | None) -> str:
        """规范化并校验知识库名称（同时用作向量库 partition 值）。"""
        name = str(raw or "").strip()
        if not name:
            raise InvalidInput("知识库名称不能为空")
        if len(name) > cls._KB_NAME_MAX:
            raise InvalidInput(f"知识库名称过长（最多 {cls._KB_NAME_MAX} 字符）")
        # 名称会进入 Milvus filter 表达式与对象存储键，故禁用引号/反斜杠等特殊字符
        if not re.fullmatch(r"[\w一-鿿\-]+", name):
            raise InvalidInput("知识库名称仅支持中文、英文、数字、下划线、连字符")
        return name

    def _kb_rows(self) -> list:
        """读取 ``knowledge_bases`` 表全部行（仓储不可用返回空）。"""
        if self._repo is None:
            return []
        try:
            return self._repo.find(self._KB_COLLECTION, order_by="id") or []
        except Exception as e:  # noqa: BLE001
            logger.warning(f"读取知识库目录失败: {e}")
            return []

    def _kb_stats_by_partition(self) -> dict[str, dict]:
        """按分区统计向量库中的切块数 / 文档数（向量库不可用返回空）。"""
        vs = self._vector
        if vs is None or not getattr(vs, "is_available", lambda: True)():
            return {}
        stats: dict[str, dict] = {}
        try:
            metadata = vs.metadata or []
        except Exception:  # noqa: BLE001
            return {}
        for m in metadata:
            part = str(m.get("partition") or "").strip()
            if not part:
                continue
            bp = stats.setdefault(part, {"chunks": 0, "sources": set()})
            bp["chunks"] += 1
            src = m.get("source")
            if src:
                bp["sources"].add(src)
        return stats

    def list_knowledge_bases(self, *, keyword: str | None = None) -> list[dict]:
        """列出所有知识库（以 ``knowledge_bases`` 表为准），附带向量库统计。

        向量库中存在但表中没有的**遗留分区**（如旧的 ``__system__``）也会列出，
        以免历史数据在管理端"消失"；这类条目标记 ``managed=False``。

        Args:
            keyword: 模糊搜索词（对**名称 + 描述**做不区分大小写的子串匹配）。
        """
        stats = self._kb_stats_by_partition()
        items: list[dict] = []
        seen: set[str] = set()
        for row in self._kb_rows():
            name = str(getattr(row, "id", "") or "")
            if not name:
                continue
            seen.add(name)
            st = stats.get(name, {"chunks": 0, "sources": set()})
            items.append({
                "name": name,
                "description": getattr(row, "description", "") or "",
                "chunks": st["chunks"],
                "documents": len(st["sources"]),
                "created_at": getattr(row, "created_at", "") or "",
                "updated_at": getattr(row, "updated_at", "") or "",
                "managed": True,
            })
        # 遗留分区（未在表中登记）：只读展示
        for name, st in stats.items():
            if name in seen:
                continue
            items.append({
                "name": name,
                "description": "",
                "chunks": st["chunks"],
                "documents": len(st["sources"]),
                "created_at": "",
                "updated_at": "",
                "managed": False,
            })

        kw = (keyword or "").strip().lower()
        if kw:
            items = [i for i in items
                     if kw in i["name"].lower() or kw in i["description"].lower()]
        return sorted(items, key=lambda x: x["name"])

    def list_knowledge_bases_page(self, *, page: int = 1, page_size: int = 0,
                                  keyword: str | None = None) -> dict:
        """知识库分页列表（信封：``total`` / ``page`` / ``page_size`` / ``knowledge_bases``）。"""
        return paginate(
            self.list_knowledge_bases(keyword=keyword),
            page, page_size, key="knowledge_bases",
        )

    def get_knowledge_base(self, name: str) -> dict | None:
        """按名称取知识库记录；不存在返回 None。"""
        if self._repo is None:
            return None
        try:
            return self._repo.get(self._KB_COLLECTION, str(name or "").strip())
        except Exception:  # noqa: BLE001
            return None

    def create_knowledge_base(self, name: str, description: str = "") -> dict:
        """创建知识库（写入 ``knowledge_bases`` 表；向量库分区在首次入库文档时出现）。"""
        name = self._normalize_kb_name(name)
        if self._repo is None:
            raise InvalidInput("知识库存储不可用（缺少数据库仓储）")
        if self.get_knowledge_base(name) is not None:
            raise InvalidInput(f"知识库 '{name}' 已存在")
        now = datetime.now().isoformat(timespec="seconds")
        self._repo.insert(self._KB_COLLECTION, KnowledgeBase(
            id=name,
            description=str(description or "").strip(),
            created_at=now,
            updated_at=now,
        ))
        logger.info(f"知识库已创建: {name}")
        return {"name": name, "description": description, "message": "知识库创建成功"}

    def update_knowledge_base(self, name: str, new_name: str | None = None,
                              description: str | None = None) -> dict:
        """更新知识库（改名 / 改描述）。

        改名会把**向量**（partition 字段）与**对象存储前缀**
        （``uploads/{old}/`` → ``uploads/{new}/``）一并迁移，使文档与解析产物不丢。
        """
        old = str(name or "").strip()
        row = self.get_knowledge_base(old)
        if row is None:
            raise NotFound(f"知识库不存在: {old}")
        desc = row.description if description is None else str(description).strip()
        target = self._normalize_kb_name(new_name) if new_name else old

        if target != old:
            if self.get_knowledge_base(target) is not None:
                raise InvalidInput(f"知识库 '{target}' 已存在")
            self._migrate_partition(old, target)
            # 改主键：删除旧行后写入新行（保留创建时间）
            self._repo.delete(self._KB_COLLECTION, old)
            now = datetime.now().isoformat(timespec="seconds")
            self._repo.insert(self._KB_COLLECTION, KnowledgeBase(
                id=target, description=desc,
                created_at=row.created_at or now, updated_at=now,
            ))
            logger.info(f"知识库已重命名: {old} → {target}")
            return {"name": target, "description": desc, "message": "知识库已重命名"}

        self._repo.update(self._KB_COLLECTION, old,
                          {"description": desc, "updated_at": datetime.now().isoformat(timespec="seconds")})
        return {"name": old, "description": desc, "message": "知识库已更新"}

    def _migrate_partition(self, old: str, new: str) -> None:
        """把某知识库的向量 partition 与对象存储前缀从 ``old`` 迁到 ``new``。

        - **对象存储**：逐个对象拷贝到新前缀后再删旧前缀（保留原文件与 chunk 产物）；
        - **向量库**：Milvus 不支持更新标量字段，按 partition 删除后重新入库
          （文档 metadata 已带 ``partition``，重新嵌入即可）。
        """
        # 1) 对象存储：拷贝 → 删旧
        try:
            objs = self._files.list_all(f"uploads/{old}")
            if objs:
                store = self._files.os
                for obj in objs:
                    src_key = obj["name"]
                    data = self._files.get_bytes(src_key)
                    if data is None:
                        continue
                    store.put_bytes(f"uploads/{new}/" + src_key[len(f"uploads/{old}/"):], data)
                self._files.delete_prefix(f"uploads/{old}")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"迁移对象存储前缀失败 {old} → {new}: {e}")

        # 2) 向量库：删旧分区数据（文档可通过重新上传恢复；此处不自动重嵌入）
        vs = self._vector
        if vs is None or not getattr(vs, "is_available", lambda: True)():
            return
        try:
            sources = [
                m.get("source") for m in (vs.metadata or [])
                if str(m.get("partition") or "") == old and m.get("source")
            ]
            if sources:
                vs.delete_by_sources(sorted(set(sources)))
                logger.info(f"知识库 {old} 的 {len(set(sources))} 篇文档向量已清除，"
                            "对象存储文件已迁移到新名称（如需向量请重新上传）")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"迁移向量分区失败 {old} → {new}: {e}")

    def delete_knowledge_base(self, name: str) -> dict:
        """删除知识库及其全部数据（向量 + 原文件 + chunk 产物 + 目录记录）。"""
        name = str(name or "").strip()
        if not name:
            raise InvalidInput("知识库名称不能为空")

        # 1) 向量库：按 partition 删除该库所有切块
        vs = self._vector
        if vs is not None and getattr(vs, "is_available", lambda: True)():
            try:
                sources = [
                    m.get("source") for m in (vs.metadata or [])
                    if str(m.get("partition") or "") == name and m.get("source")
                ]
                for src in sorted(set(sources)):
                    self._vector.delete_by_sources([src])
            except Exception as e:  # noqa: BLE001
                logger.warning(f"删除知识库向量失败 {name}: {e}")

        # 2) 对象存储：原文件 + chunk 产物
        try:
            self._files.delete_prefix(f"uploads/{name}")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"删除知识库对象失败 {name}: {e}")

        # 3) 目录记录
        if self._repo is not None:
            try:
                self._repo.delete(self._KB_COLLECTION, name)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"删除知识库目录记录失败 {name}: {e}")

        logger.info(f"知识库已删除: {name}")
        return {"message": f"知识库 '{name}' 及其所有数据已删除", "name": name}

    # ── 切块浏览 ──

    def chunks(self, *, page: int = 1, page_size: int = 20,
               source: str | None = None, partition: str | None = None,
               chunk_type: str | None = None, query_text: str | None = None) -> dict:
        """切块详情列表（分页 + 可选过滤）。

        ``partition`` 为知识库名；留空返回全部分区的切块。
        """
        vs = self._vector
        metadata = (vs.metadata if vs else []) or []

        filtered = metadata
        if source:
            filtered = [m for m in filtered if m.get("source") == source]
        if partition:
            filtered = [m for m in filtered if m.get("partition") == partition]
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
            "partition": m.get("partition", ""),   # 所属知识库
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

    # ── 文档（按知识库分区管理） ──

    def _chunk_counts(self, partition: str | None = None) -> dict[str, int]:
        """按来源统计切块数；``partition`` 为空则统计所有分区。"""
        counts: dict[str, int] = {}
        for m in (self._vector.metadata if self._vector else []) or []:
            if partition is not None and m.get("partition") != partition:
                continue
            src = m.get("source")
            if src:
                counts[src] = counts.get(src, 0) + 1
        return counts

    def list_system_docs(self, *, partition: str | None = None, keyword: str | None = None,
                         page: int = 1, page_size: int = 0) -> dict:
        """列出已入库文档（分页）：向量库中的来源、所属知识库与切块数。

        - 以**向量库**为准——只有真正切块入库的文档才会出现（chunks>0）；
        - ``partition`` 留空则返回**全部知识库**的文档，并在每行带上所属库；
        - ``keyword`` 对**文件名 / 知识库名**做不区分大小写的模糊匹配；
        - MinIO 原始文件清单（含未入库文件）见 :meth:`list_system_raw_files`。
        """
        stats: dict[str, dict] = {}
        for m in (self._vector.metadata if self._vector else []) or []:
            part = m.get("partition")
            if partition and part != partition:
                continue
            src = m.get("source")
            if not src:
                continue
            st = stats.setdefault(src, {"chunks": 0, "parts": set()})
            st["chunks"] += 1
            if part:
                st["parts"].add(part)

        kw = (keyword or "").strip().lower()
        items = [
            {
                "name": s,
                "chunks": st["chunks"],
                # 同名文档可能分布在多个知识库，全部列出
                "partitions": sorted(st["parts"]),
                "partition": partition or (sorted(st["parts"])[0] if st["parts"] else ""),
            }
            for s, st in stats.items()
        ]
        if kw:
            items = [
                i for i in items
                if kw in i["name"].lower()
                or any(kw in p.lower() for p in i["partitions"])
            ]
        items.sort(key=lambda i: i["name"])
        return paginate(items, page, page_size, key="documents")

    def list_system_raw_files(self, *, partition: str | None = None,
                              page: int = 1, page_size: int = 0) -> dict:
        """列出上传到 MinIO ``uploads/__system__/`` 的原始文件（分页）。

        以**对象存储实际文件**为准（含未成功向量化的文件——chunks=0），
        是否已入库（``imported`` / ``chunks``）从向量库统计。
        """
        part = partition or SYSTEM_PARTITION
        prefix = f"uploads/{part}/"
        names: set[str] = set()
        for obj in self._files.list_all(prefix):
            name = obj["name"]
            if "/chunk_out/" in name or not name.startswith(prefix):
                continue
            fname = name[len(prefix):]
            if fname:
                names.add(fname)
        chunk_counts = self._chunk_counts(part)
        items = [
            {
                "name": s,
                "chunks": chunk_counts.get(s, 0),
                "imported": chunk_counts.get(s, 0) > 0,
                "partition": part,
            }
            for s in sorted(names)
        ]
        return paginate(items, page, page_size, key="files")

    # ── MD 切块可视化（按页展示文档 md，标记每页内的切块边界） ──

    @staticmethod
    def _segment_text(typ: str, block: dict) -> str:
        """取块的展示文本（与向量化逻辑口径一致）。"""
        from infra.adapters.pdf.mineru_impl import (
            _SKIP_BLOCK_TYPES,
            _block_table_html,
            _block_text,
            _runs_to_text,
            _table_html_to_md,
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

    def md_view(self, source: str, partition: str | None = None) -> dict:
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
        part = partition or SYSTEM_PARTITION

        vs = self._vector
        if vs is None or not getattr(vs, "is_available", lambda: True)():
            return {"available": False, "reason": "向量存储未初始化或连接失败"}

        meta_by_page_id: dict[tuple[int, str], dict] = {}
        for m in (vs.metadata or []):
            if m.get("source") == name and m.get("id") and m.get("partition") == part:
                meta_by_page_id[(int(m.get("page") or 0), m["id"])] = m

        mid_key = None
        for obj in self._files.list_all(f"uploads/{part}/chunk_out/{stem}"):
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
            for obj in self._files.list_all(f"uploads/{part}/chunk_out/{stem}")
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

    def _view_chunks(self, name: str, partition: str | None = None) -> tuple[list, dict]:
        """读取文档 middle_json，按与入库一致的规则重放分块。

        Returns:
            ``(pages, block_map)``；block_map 键为 ``(page, bidx)``。
        """
        part = partition or SYSTEM_PARTITION
        stem = Path(os.path.basename(name)).stem
        mid_key = next(
            (o["name"] for o in self._files.list_all(
                f"uploads/{part}/chunk_out/{stem}")
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
            for obj in self._files.list_all(f"uploads/{part}/chunk_out/{stem}")
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

    def mdview_embed(self, source: str, page: int, block_idx: int,
                     partition: str | None = None) -> dict:
        """把文档视图中未嵌入的指定块手动嵌入向量库。"""
        part = partition or SYSTEM_PARTITION
        pages, block_map = self._view_chunks(source, part)
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
            "partition": part,
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
                f"uploads/{part}/chunk_out/{stem}/{ip}")
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
                "page": pno, "block_idx": bidx, "chunk_type": ctype,
                "partition": part}

    def mdview_remove(self, source: str, page: int, block_idx: int,
                      partition: str | None = None) -> dict:
        """把文档视图中已嵌入块的向量从库里移除（不动 middle_json/图片）。"""
        pages, block_map = self._view_chunks(source, partition)
        pno, bidx = int(page), int(block_idx)
        chunk = block_map.get((pno, bidx))
        if chunk is None:
            raise NotFound(f"第 {pno} 页第 {bidx} 块不存在")
        did = self._chunk_doc_id(chunk)
        self._vector.delete_by_doc_ids([did])
        return {"message": "已从向量库移除", "doc_id": did,
                "chunk_type": str(chunk.get("chunk_type") or "")}

    def upload_system(self, files_data: list[tuple[str, bytes, str]], partition: str) -> dict:
        """上传文档到指定知识库并后台解析入库，立即返回任务 ID。

        Args:
            files_data: ``[(filename, content_bytes, content_type), ...]``。
            partition: 知识库名（**必填**，无默认知识库）；须已创建。
        """
        if not files_data:
            raise ValueError("未提供文件")
        partition = self._normalize_kb_name(partition)
        if self.get_knowledge_base(partition) is None:
            raise InvalidInput(
                f"知识库 '{partition}' 不存在，请先在「数据管理 → 知识库管理」中创建"
            )

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
                "partition": partition,
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
            threading.Thread(target=self._run_upload, args=(task_id, prepared, partition), daemon=True).start()

        return {"task_id": task_id, "message": f"已接收 {len(prepared)} 个文件，后台向量化处理中（分区：{partition}）",
                "files": [p[0] for p in prepared]}

    def _run_upload(self, task_id: str, prepared: list[tuple[str, bytes]], partition: str) -> None:
        task = self._tasks[task_id]

        def _one(fname: str, content: bytes) -> None:
            # 覆盖入库：先删同名向量与旧产物，再落盘 + 解析（复用 DocumentService.upload）
            with self._lock:
                task["files"][fname] = "processing"
            try:
                self._docs.upload(partition, fname, content)
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

    def delete(self, source: str, partition: str | None = None) -> None:
        """删除指定文档（向量 + 原文件 + chunk 产物）。

        ``partition`` 非空时只清理该知识库下的副本，避免同名文档跨库误删。
        """
        if not source:
            raise ValueError("缺少参数 source")
        self._vector.delete_by_sources([source], partition)
        self._docs.purge(partition or SYSTEM_PARTITION, [source])

    def delete_raw_file(self, source: str, partition: str | None = None) -> dict:
        """仅删除该知识库下的原始文件；向量与切块产物保留。"""
        if not source:
            raise ValueError("缺少参数 source")
        name = os.path.basename(source)
        part = partition or SYSTEM_PARTITION
        self._files.delete(f"uploads/{part}/{name}")
        return {"message": f"已删除原始文件 {name}（向量/切块保留）"}
