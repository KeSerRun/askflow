"""adapters.vector.milvus —— Milvus 向量库（ports.VectorStore 实现）。

与 FaissVectorStore 语义对齐：分区/来源字段过滤 + 去重检索。
相似度使用 COSINE（等价于 Faiss 的 L2 归一化 + 内积）。
"""

from __future__ import annotations

from typing import List, Optional

import numpy as np

from core.models import Document

_QUERY_LIMIT = 64


class _Milvus:
    """pymilvus 惰性封装（避免模块导入即依赖）。"""

    def __init__(self, uri: str, token: str, alias: str = "_rag"):
        from pymilvus import connections
        self.alias = alias
        connections.connect(alias, uri=uri, token=token or None)


class MilvusVectorStore:
    """基于 Milvus 的向量库实现。"""

    def __init__(
        self,
        embedder: object,
        uri: str,
        token: str = "",
        collection_name: str = "rag_chunks",
        default_top_k: int = 10,
        alias: str = "_rag",
    ):
        """初始化。

        Args:
            embedder: 嵌入端口。
            uri: Milvus 连接地址（http://host:port）。
            token: 鉴权 token（可选）。
            collection_name: 向量集合名。
            default_top_k: search 默认值。
            alias: pymilvus 连接别名。
        """
        self._m = _Milvus(uri, token, alias)
        self._embedder = embedder
        self.dimension = embedder.dimension
        self.default_top_k = default_top_k
        self._name = collection_name
        self._collection = self._ensure_collection()

    # ── 集合管理 ──

    def _ensure_collection(self):
        from pymilvus import Collection, utility

        if utility.has_collection(self._name, using=self._m.alias):
            return Collection(self._name, using=self._m.alias)
        self._create_collection()
        return Collection(self._name, using=self._m.alias)

    def _create_collection(self) -> None:
        from pymilvus import Collection, CollectionSchema, DataType, FieldSchema

        fields = [
            FieldSchema(name="doc_id", dtype=DataType.VARCHAR, is_primary=True, max_length=64),
            FieldSchema(name="text", dtype=DataType.VARCHAR, max_length=65535),
            FieldSchema(name="source", dtype=DataType.VARCHAR, max_length=512),
            FieldSchema(name="partition", dtype=DataType.VARCHAR, max_length=128),
            FieldSchema(name="chunk_type", dtype=DataType.VARCHAR, max_length=32),
            FieldSchema(name="page", dtype=DataType.INT64),
            FieldSchema(name="img_path", dtype=DataType.VARCHAR, max_length=1024),
            FieldSchema(name="footnote", dtype=DataType.VARCHAR, max_length=65535),
            FieldSchema(name="timestamp", dtype=DataType.VARCHAR, max_length=64),
            FieldSchema(name="vector", dtype=DataType.FLOAT_VECTOR, dim=self.dimension),
        ]
        schema = CollectionSchema(fields, description="RAG document chunks")
        col = Collection(self._name, schema=schema, using=self._m.alias)
        col.create_index(
            "vector",
            {"index_type": "HNSW", "metric_type": "COSINE",
             "params": {"M": 16, "efConstruction": 256}},
            using=self._m.alias,
        )
        col.flush()
        self._collection = col
        self._collection.load()

    def _load_if_needed(self) -> None:
        if self._collection.is_empty is False and not self._collection.is_loaded:
            self._collection.load()

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

    def add_documents(self, documents: List[Document], partition: Optional[str] = None) -> None:
        import hashlib
        from datetime import datetime

        if not documents:
            return
        texts = [
            "\n".join(p for p in (
                doc.metadata.get("source", ""),
                doc.page_content,
                doc.metadata.get("footnote", ""),
            ) if p)
            for doc in documents
        ]
        vecs = self._embed(texts)
        if vecs.size == 0:
            return

        rows = []
        for i, doc in enumerate(documents):
            text_hash = hashlib.md5(doc.page_content.encode("utf-8")).hexdigest()
            rows.append({
                "doc_id": text_hash,
                "text": doc.page_content,
                "source": doc.metadata.get("source", ""),
                "partition": partition or "",
                "chunk_type": doc.metadata.get("chunk_type", ""),
                "page": doc.metadata.get("page") or 0,
                "img_path": doc.metadata.get("img_path", "") or "",
                "footnote": doc.metadata.get("footnote", "") or "",
                "timestamp": doc.metadata.get("timestamp", datetime.now().isoformat()),
                "vector": [float(v) for v in vecs[i]],
            })
        self._collection.insert(rows)
        self._collection.flush()

    # ── 管理 ──

    def get_sources_by_partition(self, partition: Optional[str] = None) -> List[str]:
        expr = _part_expr(partition)
        sources: set[str] = set()
        step, offset = 512, 0
        while True:
            rows = self._collection.query(
                expr=expr, output_fields=["source"], limit=step, offset=offset,
            )
            if not rows:
                break
            for r in rows:
                if r.get("source"):
                    sources.add(r["source"])
            offset += step
        return list(sources)

    def delete_by_partition(self, partition: Optional[str] = None) -> None:
        self._collection.delete(_part_expr(partition))

    def delete_by_sources(self, sources: List[str], *, partition: Optional[str] = None) -> None:
        if not sources:
            return
        expr = f'source in {sources!r}'
        if partition:
            expr = f'source in {sources!r} and {_part_expr(partition)}'
        self._collection.delete(expr)
        self._collection.flush()

    def count(self) -> int:
        return self._collection.num_entities

    # ── 兼容别名（工具 handler 调用旧方法名 get_documents_by_partition 等） ──

    def get_documents_by_partition(self, partition: Optional[str] = None) -> List[str]:
        return self.get_sources_by_partition(partition)

    def delete_documents_by_sources(self, sources, partition: Optional[str] = None) -> None:
        self.delete_by_sources(list(sources), partition=partition)

    def delete_documents_by_partition(self, partition: Optional[str] = None) -> None:
        self.delete_by_partition(partition)

    def store_documents_from_dir(self, directory, partition: Optional[str] = None) -> None:
        from infra.adapters.pdf.document_loader import process_documents_from_dir

        docs = process_documents_from_dir(directory)
        if not docs:
            raise RuntimeError(f"未从 {directory} 解析到任何文档")
        self.add_documents(docs, partition=partition)

    # ── 检索 ──

    def search(
        self,
        query: str,
        top_k: int = 10,
        *,
        partition: Optional[str] = None,
        source_filter: Optional[str] = None,
    ) -> List[Document]:
        top_k = top_k or self.default_top_k
        q_arr = self._embed([query])
        if q_arr.size == 0:
            return []

        expr_parts = []
        if partition:
            expr_parts.append(_part_expr(partition))
        if source_filter:
            expr_parts.append(f'source == "{_esc(source_filter)}"')
        expr = " and ".join(expr_parts) or None

        res = self._collection.search(
            data=[q_arr[0].tolist()],
            anns_field="vector",
            param={"metric_type": "COSINE", "params": {"nprobe": 10}},
            limit=min(top_k, _QUERY_LIMIT),
            expr=expr,
            output_fields=["text", "source", "partition", "chunk_type", "page",
                           "img_path", "footnote"],
        )
        if not res or not res[0]:
            return []

        docs: List[Document] = []
        seen: set[str] = set()
        for hit in res[0]:
            entity = hit.entity or {}
            page_content = entity.get("text", "")
            if page_content and page_content not in seen:
                seen.add(page_content)
                docs.append(Document(
                    page_content=page_content,
                    metadata={
                        "source": entity.get("source", ""),
                        "chunk_type": entity.get("chunk_type", ""),
                        "page": entity.get("page"),
                        "img_path": entity.get("img_path", ""),
                        "footnote": entity.get("footnote", ""),
                        "score": hit.score,
                    },
                ))
            if len(docs) >= top_k:
                break
        return docs


def _part_expr(partition: Optional[str]) -> str:
    if partition is None:
        return 'partition != "__none__" or partition == "__none__"'  # 恒真
    return f'partition == "{_esc(partition)}"'


def _esc(value: str) -> str:
    """转义 Milvus expr 字符串中的引号。"""
    return value.replace('"', '\\"')