"""adapters.pdf.document_loader —— 文档加载管线。

从 MinerU 解析输出目录构建 Document 列表，供向量入库使用。
Document 类型统一来自 base.models。
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import List

from config import conf
from infra.logger import logger
from core.models import Document

from .mineru_impl import MinerUPDFLoader


document_loaders = {
    "pdf": MinerUPDFLoader,
}


def load_sigle_document(root, file_name):
    """加载单个文档文件。

    根据文件扩展名选择对应的加载器。

    Args:
        root: 文件所在目录。
        file_name: 文件名。

    Returns:
        Document 列表，失败返回 None。
    """
    supported_extensions = document_loaders.keys()
    ext = file_name.split(".")[-1].lower()
    if ext in supported_extensions:
        file_path = os.path.join(root, file_name)
        try:
            loader_class = document_loaders[ext]
            loader = loader_class(file_path)
            doc = loader.load()
            for d in doc:
                d.metadata["file_path"] = file_path
                d.metadata["source"] = file_name
                d.metadata["extension"] = ext
                d.metadata["timestamp"] = datetime.now().isoformat()
            logger.debug(f"成功加载文档: {file_path}")
            return doc
        except Exception as e:
            logger.error(f"加载文档失败: {file_path}, 错误: {e}")
    else:
        logger.warning(f"不支持的文件类型: {file_name}")
    return None


def load_documents_from_dir(directory):
    """递归加载目录下所有支持的文档。

    Args:
        directory: 文档目录路径。

    Returns:
        拼接后的 Document 列表。
    """
    documents = []
    for root, _, files in os.walk(directory):
        for file in files:
            doc = load_sigle_document(root, file)
            if doc:
                documents.extend(doc)
    return documents


def load_documents_from_file(file_path):
    """加载单个文档文件。

    Args:
        file_path: 文件路径。

    Returns:
        Document 列表，失败返回空列表。
    """
    doc = load_sigle_document(os.path.dirname(file_path), os.path.basename(file_path))
    return doc if doc else []


def process_documents_from_dir(directory) -> List[Document]:
    """加载文档，每个 MinerU 原始块直接入库。

    对 text 类型块执行最短长度过滤和停用词过滤。

    Args:
        directory: 文档目录或文件路径。

    Returns:
        处理后的 Document 列表。
    """
    if os.path.isdir(directory):
        documents = load_documents_from_dir(directory)
    elif os.path.isfile(directory):
        documents = load_documents_from_file(directory)
    else:
        logger.error(f"无效的路径: {directory}")
        return []
    logger.debug(f"加载的文档数量: {len(documents)}")

    min_len = conf.retrieval_min_chunk
    before = len(documents)
    documents = [
        d for d in documents
        if d.metadata.get("chunk_type") != "text" or len(d.page_content) >= min_len
    ]
    if before != len(documents):
        logger.debug(f"过滤短文本块: {before} → {len(documents)} (最短 {min_len} 字符)")

    stop_words = conf.retrieval_stop_words
    before = len(documents)
    documents = [
        d for d in documents
        if d.metadata.get("chunk_type") != "text"
        or not any(w in d.page_content for w in stop_words)
    ]
    if before != len(documents):
        logger.debug(f"过滤停用词块: {before} → {len(documents)}")

    logger.info(f"文档处理完成, 共 {len(documents)} 个块")
    return documents