"""adapters.vector.milvus —— Milvus 向量库（ports.VectorStore 实现，MilvusClient API）。

相似度使用 COSINE；元数据带来源字段，检索支持来源过滤 + 去重。
"""

from __future__ import annotations

from typing import List, Optional

import numpy as np

from core.models import Document

_QUERY_LIMIT = 64
# Milvus 单次 query 的 (offset+limit) 上限
_QUERY_MAX_WINDOW = 16384


class MilvusVectorStore:
    """基于 Milvus 的向量库实现（pymilvus.MilvusClient，兼容 3.x）。"""

    def __init__(
        self,
        embedder: object,
        uri: str,
        token: str = "",
        collection_name: str = "rag_chunks",
        default_top_k: int = 10,
        parent_store: object = None,
    ):
        """初始化。

        Args:
            embedder: 嵌入端口。
            uri: Milvus 连接地址（http://host:port）。
            token: 鉴权 token（可选）。
            collection_name: 向量集合名。
            default_top_k: search 默认值。
            parent_store: 父块内容存储（save_parent(parent_id, text)）；None 则不持久化父块全文。
        """
        from pymilvus import MilvusClient

        self._client = MilvusClient(uri=uri, token=token or None)
        self._embedder = embedder
        self.dimension = embedder.dimension
        self.default_top_k = default_top_k
        self._name = collection_name
        self.parent_store = parent_store
        self._ensure_collection()

    # ── 集合管理 ──

    def _ensure_collection(self) -> None:
        from pymilvus import CollectionSchema, DataType, FieldSchema

        if self._client.has_collection(self._name):
            # 嵌入维度变化（换模型）或缺列（schema 演进）时自动重建集合（旧向量清空）
            existing = self._existing_dim()
            cols = self._existing_columns()
            need_rebuild = (
                (existing is not None and int(existing) != int(self.dimension))
                or "caption" not in cols
                or "parent_id" not in cols
            )
            if need_rebuild:
                from infra.util.logger import logger
                logger.warning(
                    f"集合 {self._name} 维度 {existing}≠{self.dimension} 或缺 caption 列，重建集合（旧向量清空）"
                )
                try:
                    self._client.drop_collection(self._name)
                except Exception:  # noqa: BLE001
                    pass
            else:
                self._load_if_possible()
                return

        fields = [
            FieldSchema(name="doc_id", dtype=DataType.VARCHAR, is_primary=True, max_length=64),
            FieldSchema(name="text", dtype=DataType.VARCHAR, max_length=65535),
            FieldSchema(name="source", dtype=DataType.VARCHAR, max_length=512),
            FieldSchema(name="partition", dtype=DataType.VARCHAR, max_length=128),
            FieldSchema(name="chunk_type", dtype=DataType.VARCHAR, max_length=32),
            FieldSchema(name="page", dtype=DataType.INT64),
            FieldSchema(name="img_path", dtype=DataType.VARCHAR, max_length=1024),
            FieldSchema(name="caption", dtype=DataType.VARCHAR, max_length=1024),
            FieldSchema(name="footnote", dtype=DataType.VARCHAR, max_length=65535),
            FieldSchema(name="parent_id", dtype=DataType.VARCHAR, max_length=64),
            FieldSchema(name="timestamp", dtype=DataType.VARCHAR, max_length=64),
            FieldSchema(name="vector", dtype=DataType.FLOAT_VECTOR, dim=self.dimension),
        ]
        schema = CollectionSchema(fields, description="RAG document chunks")
        self._client.create_collection(self._name, schema=schema)
        from pymilvus.milvus_client.index import IndexParams

        index_params = IndexParams()
        index_params.add_index(
            field_name="vector", index_type="HNSW", metric_type="COSINE",
            params={"M": 16, "efConstruction": 256},
        )
        self._client.create_index(self._name, index_params)
        self._load_if_possible()

    def _existing_dim(self) -> int | None:
        """读取现有集合的向量维度（读取失败返回 None）。"""
        try:
            desc = self._client.describe_collection(self._name)
            for f in desc.get("fields", []) or []:
                if f.get("name") == "vector":
                    params = f.get("params") or {}
                    dim = params.get("dim") or f.get("dim")
                    if dim:
                        return int(dim)
        except Exception:  # noqa: BLE001
            return None
        return None

    def _existing_columns(self) -> set[str]:
        """读取现有集合的全部字段名（读取失败返回空集）。"""
        try:
            desc = self._client.describe_collection(self._name)
            return {f.get("name", "") for f in desc.get("fields", []) or []}
        except Exception:  # noqa: BLE001
            return set()

    def _load_if_possible(self) -> None:
        try:
            self._client.load_collection(self._name)
        except Exception:  # noqa: BLE001 未加载/加载中，便于后续触发
            pass

    # ── 嵌入 ──

    def _embed(self, texts: List[str]) -> np.ndarray:
        vecs = self._embedder.embed(texts)
        arr = np.array(vecs, dtype=np.float32)
        if arr.size and arr.ndim == 2:
            norms = np.linalg.norm(arr, axis=1, keepdims=True)
            norms[norms == 0] = 1.0
            arr = arr / norms  # COSINE 语义下归一化（可选，稳妥）
        return arr

    # ── 入库 ──

    def add_documents(self, documents: List[Document]) -> None:
        import hashlib
        from datetime import datetime

        if not documents:
            return

        # 只入「图」与「正文子块」：表格不入库；图必须有可编码的图片字节
        pool = []
        for d in documents:
            ct = (d.metadata.get("chunk_type") or "").strip()
            if ct == "table":
                continue
            if ct in ("image", "chart"):
                if d.metadata.get("img_data"):
                    pool.append(d)
                continue  # 无图片字节（如 svg/缺失）不向量化
            if not (d.page_content or "").strip():
                continue  # 空正文不入库
            pool.append(d)
        if not pool:
            return

        text_pool = [d for d in pool if not d.metadata.get("img_data")]

        # 正文子块：source+正文+footnote 拼接批量文本嵌入
        vec_text = None
        if text_pool:
            lane = ["\n".join(p for p in (
                d.metadata.get("source", ""), d.page_content, d.metadata.get("footnote", ""),
            ) if p) for d in text_pool]
            vec_text = self._embed(lane)

        now = datetime.now().isoformat()
        rows = []
        ti = 0
        for d in pool:
            meta = d.metadata or {}
            img_data = meta.get("img_data")
            if img_data:
                # 图：整图向量；caption 进 caption 列，text 留空；doc_id 用图片路径保证唯一
                vec = self._embed_image(img_data)
                img_path = meta.get("img_path", "") or ""
                rows.append({
                    "doc_id": hashlib.md5(img_path.encode("utf-8")).hexdigest(),
                    "text": "",
                    "source": meta.get("source", ""),
                    "partition": "__system__",
                    "chunk_type": meta.get("chunk_type", "") or "image",
                    "page": meta.get("page") or 0,
                    "img_path": img_path,
                    "caption": meta.get("caption", "") or "",
                    "footnote": meta.get("footnote", "") or "",
                    "parent_id": "",
                    "timestamp": meta.get("timestamp", now),
                    "vector": vec,
                })
            else:
                if not d.page_content.strip():
                    continue  # 防御：空文本不进库
                text_hash = hashlib.md5(d.page_content.encode("utf-8")).hexdigest()
                parent_id = meta.get("parent_id", "") or ""
                parent_text = meta.get("parent_text", "") or ""
                # 父块全文去重入库（只存一次）；向量库仅存 parent_id
                if parent_id and parent_text and self.parent_store is not None:
                    try:
                        self.parent_store(parent_id, parent_text)
                    except Exception:  # noqa: BLE001
                        pass
                rows.append({
                    "doc_id": text_hash,
                    "text": d.page_content,
                    "source": meta.get("source", ""),
                    "partition": "__system__",
                    "chunk_type": "text",
                    "page": meta.get("page") or 0,
                    "img_path": "",
                    "caption": "",
                    "footnote": meta.get("footnote", "") or "",
                    "parent_id": parent_id,
                    "timestamp": meta.get("timestamp", now),
                    "vector": vec_text[ti].tolist(),
                })
                ti += 1

        if rows:
            self._client.insert(self._name, rows)
            self._client.flush(self._name)

    def _embed_image(self, data: bytes) -> list[float]:
        """图片嵌入向量（与文本同空间，COSINE 前再归一化一次）。"""
        vec = self._embedder.embed_image(data)
        arr = np.array([vec], dtype=np.float32)
        norm = float(np.linalg.norm(arr[0])) or 1.0
        return (arr[0] / norm).tolist()

    def embed_image_bytes(self, data: bytes) -> list[float]:
        """公开接口：把图片字节编码为向量（图搜文/图搜图）。"""
        return self._embed_image(data)

    # ── 管理 ──

    def get_sources(self) -> List[str]:
        sources: set[str] = set()
        try:
            rows = self._client.query(
                self._name, filter="source != ''",
                output_fields=["source"], limit=_QUERY_MAX_WINDOW,
            )
            for r in rows or []:
                if r.get("source"):
                    sources.add(r["source"])
        except Exception:  # noqa: BLE001
            return []
        return sorted(sources)

    def delete_all(self) -> None:
        self._client.delete(self._name, filter='doc_id != ""')
        self._client.flush(self._name)

    def delete_by_sources(self, sources: List[str]) -> None:
        if not sources:
            return
        self._client.delete(self._name, filter=f'source in {sources!r}')
        self._client.flush(self._name)

    def delete_by_doc_ids(self, doc_ids: List[str]) -> None:
        """按向量主键 doc_id 删除指定切块。"""
        ids = [str(i) for i in doc_ids or [] if str(i)]
        if not ids:
            return
        self._client.delete(self._name, filter=f'doc_id in {ids!r}')
        self._client.flush(self._name)

    def count(self) -> int:
        return int(self._client.get_collection_stats(self._name).get("row_count", 0) or 0)

    # ── 统计 / 元数据（数据库、仪表盘读取用） ──

    _META_FIELDS = ["doc_id", "text", "source", "partition", "chunk_type",
                    "page", "img_path", "caption", "footnote", "parent_id", "timestamp"]

    @property
    def metadata(self) -> list[dict]:
        """读取 chunk 元数据（单次取满窗口；Milvus 不可用时返回空）。"""
        out: list[dict] = []
        try:
            rows = self._client.query(
                self._name, filter="doc_id != ''",
                output_fields=list(self._META_FIELDS), limit=_QUERY_MAX_WINDOW,
            )
            for r in rows or []:
                out.append({
                    "id": r.get("doc_id", ""),
                    "text": r.get("text", ""),
                    "source": r.get("source", ""),
                    "partition": r.get("partition", ""),
                    "chunk_type": r.get("chunk_type", ""),
                    "page": r.get("page"),
                    "img_path": r.get("img_path", ""),
                    "caption": r.get("caption", ""),
                    "footnote": r.get("footnote", ""),
                    "parent_id": r.get("parent_id", ""),
                    "timestamp": r.get("timestamp", ""),
                })
        except Exception:  # noqa: BLE001
            return []
        return out

    @property
    def dense_vectors(self) -> list:
        """兼容字段：Milvus 侧不导出向量，保留空列表（total_vectors 由 metadata 长度计）。"""
        return []

    # ── 兼容别名 ──

    def get_documents(self) -> List[str]:
        return self.get_sources()

    def store_documents_from_dir(self, directory) -> None:
        from infra.adapters.pdf.document_loader import process_documents_from_dir

        docs = process_documents_from_dir(directory)
        if not docs:
            raise RuntimeError(f"未从 {directory} 解析到任何文档")
        self.add_documents(docs)

    # ── 检索 ──

    def search(
        self,
        query: str,
        top_k: int = 10,
        *,
        source_filter: Optional[str] = None,
        chunk_filter: str = "mixed",
    ) -> List[Document]:
        top_k = top_k or self.default_top_k
        q_arr = self._embed([query])
        if q_arr.size == 0:
            return []

        conds = []
        if source_filter:
            conds.append(f'source == "{_esc(source_filter)}"')
        if chunk_filter == "text":
            conds.append('chunk_type == "text"')
        elif chunk_filter == "image":
            conds.append('chunk_type in ["image", "chart"]')
        expr = " and ".join(conds) if conds else None

        res = self._client.search(
            self._name,
            data=[q_arr[0].tolist()],
            anns_field="vector",
            search_params={"metric_type": "COSINE", "params": {"nprobe": 10}},
            limit=min(top_k, _QUERY_LIMIT),
            filter=expr or "",
            output_fields=["text", "source", "chunk_type", "page",
                           "img_path", "footnote"],
        )
        if not res or not res[0]:
            return []

        docs: List[Document] = []
        seen: set[str] = set()
        for hit in res[0]:
            entity = (hit or {}).get("entity") or {}
            page_content = entity.get("text", "") or entity.get("caption", "")
            if not page_content and entity.get("chunk_type", "") in ("image", "chart"):
                page_content = f"[图] {entity.get('img_path', '') or ''}"
            if page_content and page_content not in seen:
                seen.add(page_content)
                docs.append(Document(
                    page_content=page_content,
                    metadata={
                        "source": entity.get("source", ""),
                        "chunk_type": entity.get("chunk_type", ""),
                        "page": entity.get("page"),
                        "img_path": entity.get("img_path", ""),
                        "caption": entity.get("caption", ""),
                        "footnote": entity.get("footnote", ""),
                        "score": hit.get("distance", 0.0),
                    },
                ))
            if len(docs) >= top_k:
                break
        return docs

    def search_by_vector(
        self,
        vector,
        top_k: int = 10,
        *,
        source_filter: Optional[str] = None,
        chunk_filter: str = "mixed",
    ) -> List[Document]:
        """按给定向量检索（图搜文 / 任意同空间向量查询）。"""
        top_k = min(top_k or self.default_top_k, _QUERY_LIMIT)
        conds = []
        if source_filter:
            conds.append(f'source == "{_esc(source_filter)}"')
        if chunk_filter == "text":
            conds.append('chunk_type == "text"')
        elif chunk_filter == "image":
            conds.append('chunk_type in ["image", "chart"]')
        expr = " and ".join(conds) if conds else None
        res = self._client.search(
            self._name,
            data=[list(vector)],
            anns_field="vector",
            search_params={"metric_type": "COSINE", "params": {"nprobe": 10}},
            limit=top_k,
            filter=expr or "",
            output_fields=["text", "source", "chunk_type", "page",
                           "img_path", "footnote"],
        )
        if not res or not res[0]:
            return []

        docs: List[Document] = []
        seen: set[str] = set()
        for hit in res[0]:
            entity = (hit or {}).get("entity") or {}
            page_content = entity.get("text", "") or entity.get("caption", "")
            if not page_content and entity.get("chunk_type", "") in ("image", "chart"):
                page_content = f"[图] {entity.get('img_path', '') or ''}"
            if page_content and page_content not in seen:
                seen.add(page_content)
                docs.append(Document(
                    page_content=page_content,
                    metadata={
                        "source": entity.get("source", ""),
                        "chunk_type": entity.get("chunk_type", ""),
                        "page": entity.get("page"),
                        "img_path": entity.get("img_path", ""),
                        "caption": entity.get("caption", ""),
                        "footnote": entity.get("footnote", ""),
                        "score": hit.get("distance", 0.0),
                    },
                ))
            if len(docs) >= top_k:
                break
        return docs


def _esc(value: str) -> str:
    """转义 Milvus filter 表达式字符串中的引号。"""
    return value.replace('"', '\\"')