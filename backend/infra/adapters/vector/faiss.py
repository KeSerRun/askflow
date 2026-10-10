"""adapters.vector.faiss —— FAISS 本地向量库（ports.VectorStore 实现）。

嵌入能力经 Embedder 端口注入，数据格式与既有索引兼容（直接读取），
替换 Milvus 时业务层零改动。
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from datetime import datetime
from typing import List, Optional

import faiss
import numpy as np

from core.models import Document


class FaissVectorStore:
    """基于 FAISS 内积索引 + L2 归一化的本地向量库。"""

    def __init__(self, embedder: object, index_dir: str, default_top_k: int = 10):
        """初始化。

        Args:
            embedder: 嵌入端口（向量化能力来源）。
            index_dir: 索引持久化目录（npy + json）。
            default_top_k: search 未指定 top_k 时的默认值。
        """
        self._embedder = embedder
        self.dimension = embedder.dimension
        self.default_top_k = default_top_k
        self.index_dir = index_dir
        os.makedirs(self.index_dir, exist_ok=True)

        self._dense_file = os.path.join(self.index_dir, "dense_vectors.npy")
        self._meta_file = os.path.join(self.index_dir, "metadata.json")
        self._lock = threading.RLock()

        self.dense_vectors: List[List[float]] = []
        self.metadata: List[dict] = []
        self.dense_index: Optional[faiss.IndexFlatIP] = None

        self._load_from_disk()

    # ── 持久化 ──

    def _load_from_disk(self) -> None:
        """加载旧索引；维度不匹配时丢弃重建。"""
        if not (os.path.exists(self._dense_file) and os.path.exists(self._meta_file)):
            return
        try:
            arr = np.load(self._dense_file)
            if arr.size and arr.shape[1] != self.dimension:
                self._reset()
                return
            self.dense_vectors = arr.tolist()
            with open(self._meta_file, "r", encoding="utf-8") as f:
                self.metadata = json.load(f)
            for m in self.metadata:
                m.pop("sparse_vector", None)
            self._rebuild_index()
        except Exception:
            self._reset()

    def _reset(self) -> None:
        self.dense_vectors = []
        self.metadata = []
        self.dense_index = None

    def _save_to_disk(self) -> None:
        with self._lock:
            if self.dense_vectors:
                np.save(self._dense_file, np.array(self.dense_vectors, dtype=np.float32))
            elif os.path.exists(self._dense_file):
                os.remove(self._dense_file)
            with open(self._meta_file, "w", encoding="utf-8") as f:
                json.dump(self.metadata, f, ensure_ascii=False, indent=2)

    def _rebuild_index(self) -> None:
        if self.dense_vectors:
            arr = np.array(self.dense_vectors, dtype=np.float32)
            faiss.normalize_L2(arr)
            self.dense_vectors = arr.tolist()
            self.dense_index = faiss.IndexFlatIP(self.dimension)
            self.dense_index.add(arr)
        else:
            self.dense_index = None

    def _embed(self, texts: List[str]) -> np.ndarray:
        """调用 Embedder 端口嵌入并 L2 归一化。"""
        vectors = self._embedder.embed(list(texts))
        arr = np.array(vectors, dtype=np.float32)
        if arr.size and arr.ndim == 2:
            faiss.normalize_L2(arr)
        return arr

    # ── 入库 ──

    def add_documents(self, documents: List[Document], partition: Optional[str] = None) -> None:
        if not documents:
            return
        parts = [
            "\n".join(p for p in (
                doc.metadata.get("source", ""),
                doc.page_content,
                doc.metadata.get("footnote", ""),
            ) if p)
            for doc in documents
        ]
        try:
            embeddings = self._embed(parts)
        except Exception:
            return
        if embeddings.size == 0:
            return

        with self._lock:
            for i, doc in enumerate(documents):
                text_hash = hashlib.md5(doc.page_content.encode("utf-8")).hexdigest()
                self.dense_vectors.append(embeddings[i].tolist())
                self.metadata.append({
                    "id": text_hash,
                    "text": doc.page_content,
                    "source": doc.metadata.get("source", ""),
                    "timestamp": doc.metadata.get("timestamp", datetime.now().isoformat()),
                    "partition": partition or "",
                    "chunk_type": doc.metadata.get("chunk_type", ""),
                    "page": doc.metadata.get("page"),
                    "img_path": doc.metadata.get("img_path") if doc.metadata.get("chunk_type") != "table" else "",
                    "footnote": doc.metadata.get("footnote", ""),
                    "table_body": doc.metadata.get("table_body", ""),
                })
            if self.dense_index is None:
                self.dense_index = faiss.IndexFlatIP(self.dimension)
            self.dense_index.add(embeddings)
            self._save_to_disk()

    # ── 管理 ──

    def get_sources_by_partition(self, partition: Optional[str] = None) -> List[str]:
        if partition:
            sources = {m["source"] for m in self.metadata if m["partition"] == partition}
        else:
            sources = {m["source"] for m in self.metadata}
        return list(sources)

    def delete_by_partition(self, partition: Optional[str] = None) -> None:
        with self._lock:
            keep = [i for i, m in enumerate(self.metadata)
                    if partition and m["partition"] != partition]
            self._apply_keep_indices(keep)

    def delete_by_sources(self, sources: List[str], *, partition: Optional[str] = None) -> None:
        with self._lock:
            before = len(self.metadata)
            keep = []
            for i, m in enumerate(self.metadata):
                if m["source"] in sources:
                    if partition and m["partition"] != partition:
                        keep.append(i)
                else:
                    keep.append(i)
            self._apply_keep_indices(keep)
            before - len(self.metadata)

    def _apply_keep_indices(self, keep_indices: List[int]) -> None:
        keep_set = set(keep_indices)
        self.dense_vectors = [v for i, v in enumerate(self.dense_vectors) if i in keep_set]
        self.metadata = [m for i, m in enumerate(self.metadata) if i in keep_set]
        if self.dense_vectors:
            arr = np.array(self.dense_vectors, dtype=np.float32)
            self.dense_index = faiss.IndexFlatIP(self.dimension)
            self.dense_index.add(arr)
        else:
            self.dense_index = None
        self._save_to_disk()

    # ── 兼容别名（工具 handler / 既有调用点使用 get_documents_by_partition 等旧名） ──

    def get_documents_by_partition(self, partition: Optional[str] = None) -> List[str]:
        """旧名：get_sources_by_partition。"""
        return self.get_sources_by_partition(partition)

    def delete_documents_by_sources(self, sources, partition: Optional[str] = None) -> None:
        """旧名：delete_by_sources。"""
        self.delete_by_sources(list(sources), partition=partition)

    def delete_documents_by_partition(self, partition: Optional[str] = None) -> None:
        """旧名：delete_by_partition。"""
        self.delete_by_partition(partition)

    def store_documents_from_dir(self, directory, partition: Optional[str] = None) -> None:
        """从目录加载文档并入向量库。"""
        from infra.adapters.pdf.document_loader import process_documents_from_dir

        docs = process_documents_from_dir(directory)
        if not docs:
            raise RuntimeError(f"未从 {directory} 解析到任何文档")
        self.add_documents(docs, partition=partition)

    def count(self) -> int:
        return len(self.metadata)

    # ── 检索 ──

    def search(
        self,
        query: str,
        top_k: int = 10,
        *,
        partition: Optional[str] = None,
        source_filter: Optional[str] = None,
    ) -> List[Document]:
        with self._lock:
            return self._search_impl(query, top_k or self.default_top_k, partition, source_filter)

    def _search_impl(
        self,
        query: str,
        top_k: int,
        partition: Optional[str] = None,
        source_filter: Optional[str] = None,
    ) -> List[Document]:
        if not self.dense_index or not self.metadata:
            return []
        q_vec = self._embed([query])
        if q_vec.size == 0:
            return []
        search_n = min(top_k * 4, len(self.metadata))
        scores, ids = self.dense_index.search(q_vec, search_n)
        candidates = [(int(i), float(s)) for i, s in zip(ids[0], scores[0]) if i != -1]

        def keep(meta) -> bool:
            if partition and meta.get("partition", "") != partition:
                return False
            if source_filter and meta.get("source", "") != source_filter:
                return False
            return True

        filtered = [(i, s) for i, s in candidates if keep(self.metadata[i])]
        filtered = filtered[: top_k * 2]
        if not filtered:
            return []

        child_docs: List[Document] = []
        for idx, _ in filtered[:top_k]:
            m = self.metadata[idx]
            child_docs.append(Document(
                page_content=m.get("text", ""),
                metadata={
                    "id": m.get("id", ""),
                    "source": m.get("source", ""),
                    "timestamp": m.get("timestamp", ""),
                    "chunk_type": m.get("chunk_type", ""),
                    "section_path": m.get("section_path", []),
                    "page": m.get("page"),
                    "caption": m.get("caption", ""),
                    "footnote": m.get("footnote", ""),
                    "img_path": m.get("img_path", ""),
                },
            ))

        seen = set()
        unique = []
        for doc in child_docs:
            key = doc.page_content
            if key and key not in seen:
                unique.append(doc)
        return unique[:top_k]