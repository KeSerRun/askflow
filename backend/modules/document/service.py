"""modules.document.service —— 文档用例（会话附件暂存 / 系统文档入库）+ 目录配额。

- ``DocumentService``：
  - **会话附件暂存**：对话页上传的附件按 ``sessions/{user}/{session_id}/`` 隔离存放，
    只暂存、**不解析不入向量库**（解析产物为 md 供会话内工具检索）；受 ``max_session_mb`` 限制；
  - **系统文档入库**：``upload()`` 保存原始文件（MinIO）+ MinerU 解析 + 向量化（管理端使用，进 ``__system__``）；
  - **图片读取**：供答案中的图片直链（``read_image`` / ``read_image_global``）。

文件存储统一走 ``FileStore``（**仅对象存储，不读写本地 data 目录**）：
  1. 原始文件写入对象 ``uploads/{partition}/{filename}``；
  2. ``VectorStore.store_documents_from_dir`` 从临时物化文件解析入库，并把 MinerU 产物
     （chunk_out/）上传回对象 ``uploads/{partition}/chunk_out/{stem}/``，随后清理临时物化文件；
  3. 按来源删除向量，并清理对象产物。

依赖：仅具体的 vector / 对象存储适配器；``object_store`` 由组合根注入。
"""

from __future__ import annotations

import mimetypes
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

from core.app_errors import InvalidInput, NotFound, PermissionDenied, QuotaExceeded
from infra.adapters.pdf.document_loader import MINERU_EXTENSIONS
from infra.adapters.pdf.mineru_impl import MinerULoader
from .backend import FileStore, match_img_key
from .entity import UploadResult

_ILLEGAL_CHARS = re.compile(r'[\x00-\x1f\\/:*?"<>|]')
_WINDOWS_RESERVED = {
    "con", "prn", "aux", "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}
_MAX_FILENAME_BYTES = 200


class DocumentService:
    """文档处理用例。"""

    def __init__(self, vector: object, *,
                 object_store: Optional[object] = None,
                 mineru_max_concurrency: int = 3, max_session_mb: int = 0):
        """初始化。

        Args:
            vector: 向量库适配器（提供 store_documents_from_dir / delete_by_* 等）。
            object_store: 对象存储适配器（MinIO；None 表示不可用，文件读写被禁用）。
            mineru_max_concurrency: 系统文档向量化的解析并发上限。
            max_session_mb: 每会话附件暂存总大小上限（MB）；<=0 表示不限制。
        """
        self._vector = vector
        self._files = FileStore(object_store)
        self._workers = max(1, int(mineru_max_concurrency or 1))
        self._max_session_mb = max(0, int(max_session_mb or 0))
        # 会话附件 MinerU 解析状态（不入向量库）：{user|session: {filename: {"status", "error"}}}
        self._parse_states: dict[str, dict[str, dict]] = {}
        self._parse_lock = threading.Lock()

    # ── 键 ──

    @staticmethod
    def _session_user(user: str) -> str:
        """会话对象的用户键（与历史目录一致性约定：统一小写）。"""
        return str(user).lower()

    def _session_prefix(self, user: str, session_id: str) -> str:
        return f"sessions/{self._session_user(user)}/{os.path.basename(session_id)}"

    def _upload_key(self, user: str, filename: str) -> str:
        return f"uploads/{str(user)}/{os.path.basename(filename)}"

    # ── 保存（系统文档） ──

    def save_file(self, user: str, filename: str, data: bytes) -> dict:
        """保存单个原始文件（不解析，写入对象存储）。

        Returns:
            dict: ``{"filename", "size", "path"}``（path 为对象键）。
        """
        name = os.path.basename(filename)
        rel = self._upload_key(user, name)
        self._files.put(rel, data)
        return {"filename": name, "size": len(data), "path": rel}

    # ── 清理（系统文档） ──

    def purge(self, user: str, sources: Optional[list] = None) -> None:
        """清理原文件与其 chunk 产物。

        - ``sources=None``: 清空整个分区（含全部文件与 chunk_out/）
        - ``sources=[...]``: 仅清指定文件及其 ``chunk_out/{stem}/``
        """
        if sources is None:
            self._files.delete_prefix(f"uploads/{str(user)}")
            return

        for src in sources:
            name = os.path.basename(src)
            self._files.delete(self._upload_key(user, name))
            stem = os.path.splitext(name)[0]
            self._files.delete_prefix(f"uploads/{str(user)}/chunk_out/{stem}")

    # ── 入库（系统文档） ──

    def forget_source(self, user: str, filename: str) -> None:
        """删除某来源的向量（不动文件）。"""
        self._vector.delete_by_sources([os.path.basename(filename)])

    def index_file(self, user: str, filename: str) -> None:
        """解析并入库单个文件（只进系统分区），chunk 产物上传回对象存储。

        把原始文件物化到系统临时目录 → 本地解析/向量化 →
        产物上传回对象存储 → 清理临时物化文件。
        """
        name = os.path.basename(filename)
        rel = self._upload_key(user, name)
        proxy = self._files.local_materialize(rel)
        if proxy is None:
            raise NotFound(f"原文件未找到: {name}")

        self._vector.store_documents_from_dir(proxy)

        stem = Path(proxy).stem
        co = Path(proxy).parent / "chunk_out" / stem
        if co.is_dir():
            self._files.upload_subtree(str(co), f"uploads/{str(user)}/chunk_out/{stem}")
        self._files.cleanup_materialized(rel)

    def upload(self, user: str, filename: str, data: bytes) -> UploadResult:
        """保存 + 覆盖入库（先删同名向量与旧产物）。"""
        name = os.path.basename(filename)
        self.forget_source(user, name)
        self.purge(user, [name])
        self.save_file(user, name, data)
        self.index_file(user, name)
        return UploadResult(filename=name, sources=[name])

    # ── 会话附件暂存（对话页：只暂存，不解析/不入库） ──

    def _session_size_bytes(self, user: str, session_id: str) -> int:
        return self._files.size_bytes(self._session_prefix(user, session_id))

    def session_usage(self, user: str, session_id: str) -> dict:
        """会话暂存使用情况（current_mb / max_mb / limit_enabled / ok）。"""
        current_mb = round(self._session_size_bytes(user, session_id) / (1024 * 1024), 2)
        return {
            "current_mb": current_mb,
            "max_mb": self._max_session_mb,
            "limit_enabled": self._max_session_mb > 0,
            "ok": self._max_session_mb <= 0 or current_mb <= self._max_session_mb,
        }

    def save_session_files(self, user: str, session_id: str, files: list) -> list[dict]:
        """把对话页附件暂存到会话目录（只暂存，不做解析/向量化）。

        Args:
            user: 用户 ID（分区归属）。
            session_id: 会话 ID（目录隔离）。
            files: ``[(原始文件名, content_bytes, content_type), ...]``。

        Returns:
            list[dict]: 每个文件 ``{"filename", "size", "content_type"}``。

        Raises:
            AppError 413: 会话附件总大小超过上限。
            AppError 400: 文件名为空/非法。
        """
        prefix = self._session_prefix(user, session_id)
        incoming = sum(len(content) for _, content, _ in files)
        if self._max_session_mb > 0:
            current = self._session_size_bytes(user, session_id)
            if (current + incoming) > self._max_session_mb * 1024 * 1024:
                current_mb = round(current / (1024 * 1024), 2)
                raise QuotaExceeded(
                    f"会话附件空间不足：已用 {current_mb}MB / 上限 {self._max_session_mb}MB，"
                    "请清理后再上传"
                )

        results = []
        for raw_name, content, content_type in files:
            name = self.sanitize_filename(raw_name)
            self._files.put(f"{prefix}/{name}", content, content_type=content_type or "")
            results.append({"filename": name, "size": len(content), "content_type": content_type})
        return results

    def list_session_files(self, user: str, session_id: str) -> list[dict]:
        """列出会话暂存文件（``name`` / ``size``，按名排序；不含 chunk_out 产物）。"""
        return self._files.list(self._session_prefix(user, session_id))

    def delete_session_file(self, user: str, session_id: str, filename: str) -> None:
        """删除会话暂存下的单个文件（连同其解析产物与状态；不存在则忽略）。"""
        prefix = self._session_prefix(user, session_id)
        name = os.path.basename(filename)
        self._files.delete(f"{prefix}/{name}")
        stem = os.path.splitext(name)[0]
        self._files.delete_prefix(f"{prefix}/chunk_out/{stem}")
        key = self._parse_key(user, session_id)
        with self._parse_lock:
            self._parse_states.get(key, {}).pop(name, None)

    def clear_session_files(self, user: str, session_id: str) -> None:
        """清空会话暂存（含解析产物与解析状态）。"""
        self._files.delete_prefix(self._session_prefix(user, session_id))
        key = self._parse_key(user, session_id)
        with self._parse_lock:
            self._parse_states.pop(key, None)

    def read_session_file(self, user: str, session_id: str, filename: str) -> tuple[bytes, str]:
        """读取会话暂存原始文件字节（路径穿越防护：仅接受文件名）。

        Returns:
            tuple: ``(bytes, filename)``。

        Raises:
            AppError 403: 路径穿越。
            AppError 404: 文件不存在。
        """
        name = os.path.basename(filename)
        if name in ("", ".", ".."):
            raise PermissionDenied("forbidden")
        prefix = self._session_prefix(user, session_id)
        data = self._files.get_bytes(f"{prefix}/{name}")
        if data is None:
            raise NotFound("file not found")
        return data, name

    # ── 会话附件 MinerU 解析（对话页上传 → 解析为 txt，不入向量库） ──

    def _parse_key(self, user: str, session_id: str) -> str:
        return f"{self._session_user(user)}|{os.path.basename(session_id)}"

    def schedule_session_parse(self, user: str, session_id: str, filenames: list[str]) -> None:
        """为会话附件启动后台 MinerU 解析（产物上传回 ``会话目录/chunk_out/{stem}/``）。

        仅处理 MinerU 支持的格式；其余标记 ``skipped``（仅暂存，不可检索）。
        """
        key = self._parse_key(user, session_id)
        with self._parse_lock:
            states = self._parse_states.setdefault(key, {})

        def _one(fname: str) -> None:
            with self._parse_lock:
                states[fname] = {"status": "parsing", "error": ""}
            try:
                name = os.path.basename(fname)
                prefix = self._session_prefix(user, session_id)
                rel = f"{prefix}/{name}"
                proxy = self._files.local_materialize(rel)
                if proxy is None:
                    raise FileNotFoundError(fname)
                # 产物写入 proxy.parent/chunk_out/{stem}/
                MinerULoader(proxy).load()
                stem = Path(proxy).stem
                co = Path(proxy).parent / "chunk_out" / stem
                if co.is_dir():
                    self._files.upload_subtree(str(co), f"{prefix}/chunk_out/{stem}")
                self._files.cleanup_materialized(rel)
                with self._parse_lock:
                    states[fname] = {"status": "success", "error": ""}
            except Exception as e:  # noqa: BLE001
                with self._parse_lock:
                    states[fname] = {"status": "failed", "error": str(e)[:300]}

        def _text_doc(fname: str) -> None:
            """md/markdown 直接作为文本文档：原样拷贝为 chunk_out/{stem}/{stem}.txt 供会话工具读取。"""
            with self._parse_lock:
                states[fname] = {"status": "parsing", "error": ""}
            try:
                name = os.path.basename(fname)
                stem = Path(name).stem
                prefix = self._session_prefix(user, session_id)
                data = self._files.get_bytes(f"{prefix}/{name}")
                if not data:
                    raise FileNotFoundError(fname)
                self._files.put(f"{prefix}/chunk_out/{stem}/{stem}.txt", data)
                with self._parse_lock:
                    states[fname] = {"status": "success", "error": ""}
            except Exception as e:  # noqa: BLE001
                with self._parse_lock:
                    states[fname] = {"status": "failed", "error": str(e)[:300]}

        jobs: list[str] = []
        for fname in filenames:
            ext = os.path.splitext(fname)[1].lstrip(".").lower()
            if not fname:
                continue
            if ext in ("md", "markdown"):
                # 纯文本文档：不经 MinerU，直接拷贝为会话 txt
                _text_doc(fname)
                continue
            if ext not in MINERU_EXTENSIONS:
                with self._parse_lock:
                    states[fname] = {"status": "skipped", "error": ""}
                continue
            with self._parse_lock:
                states[fname] = {"status": "pending", "error": ""}
            jobs.append(fname)

        if jobs:
            with ThreadPoolExecutor(max_workers=self._workers) as pool:
                list(pool.map(_one, jobs))

    def session_parse_status(self, user: str, session_id: str) -> dict:
        """返回当前会话各附件的解析状态与用量（供对话页展示）。"""
        key = self._parse_key(user, session_id)
        with self._parse_lock:
            states = dict(self._parse_states.get(key, {}))
        return {"files": states, "usage": self.session_usage(user, session_id)}

    # ── 图片读取（供答案中的图片直链） ──

    @staticmethod
    def _media_of(name: str) -> str:
        return mimetypes.guess_type(name)[0] or "application/octet-stream"

    def read_image(self, doc_stem: str, img_name: str) -> Optional[tuple[bytes, str, str]]:
        """按 doc_stem 定位 MinerU 解析图片并读取字节。

        Returns:
            tuple ``(bytes, media_type, filename)`` 或 None。
        """
        img_name = img_name.rstrip("/")
        stems = {Path(doc_stem).name, Path(doc_stem).stem}
        for s in sorted(stems, key=len, reverse=True):
            for item in self._files.list_all(f"uploads/__system__/chunk_out/{s}"):
                if match_img_key(item["name"], img_name):
                    data = self._files.get_bytes(item["name"])
                    if data:
                        return data, self._media_of(item["name"]), os.path.basename(item["name"])
        return None

    def read_query_image(self, key: str) -> Optional[tuple[bytes, str, str]]:
        """读取对话页粘贴图片（``sessions/{user_id}/{session_id}/query_img/...``）。

        Returns:
            tuple ``(bytes, media_type, filename)`` 或 None。
        """
        key = str(key or "").lstrip("/")
        if not key:
            return None
        name = os.path.basename(key)
        data = self._files.get_bytes(key)
        if not data:
            return None
        return data, self._media_of(name), name

    def read_chunk_image(self, key: str) -> Optional[tuple[bytes, str, str]]:
        """按对象键读取 MinerU 解析图片（会话附件或系统文档的 ``chunk_out/.../images/``）。

        与会话附件/知识库图片共用同一入口：键形如
        ``sessions/{user}/{session_id}/chunk_out/{stem}/images/img_0001.png`` 或
        ``uploads/__system__/chunk_out/{stem}/images/img_0001.png``。

        Returns:
            tuple ``(bytes, media_type, filename)`` 或 None。
        """
        key = str(key or "").lstrip("/")
        if ("/chunk_out/" not in key) or ("/images/" not in key):
            return None
        if not key.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".tif", ".tiff")):
            return None
        data = self._files.get_bytes(key)
        if not data:
            return None
        return data, self._media_of(key), os.path.basename(key)

    def read_image_global(self, img_name: str) -> Optional[tuple[bytes, str, str]]:
        """全局搜索 MinerU 图片（仅有图片 hash 时使用）。

        Returns:
            tuple ``(bytes, media_type, filename)`` 或 None。
        """
        img_name = img_name.rstrip("/")
        if img_name.startswith("images/"):
            img_name = img_name[7:]
        for item in self._files.list_all("uploads/__system__/chunk_out"):
            if match_img_key(item["name"], img_name):
                data = self._files.get_bytes(item["name"])
                if data:
                    return data, self._media_of(item["name"]), os.path.basename(item["name"])
        return None

    # ── 上传校验 ──

    @staticmethod
    def sanitize_filename(raw: str) -> str:
        """清理上传文件名：去路径、去非法字符、去尾部空格/点、长度限制、拒绝保留名称。

        Raises:
            AppError 400: 清理后文件名为空、保留名或过长。
        """
        name = os.path.basename(raw)
        name = _ILLEGAL_CHARS.sub("_", name)
        name = name.rstrip(" .")

        if not name or name.startswith("."):
            raise InvalidInput(f"无效的文件名: {raw}")

        stem = name.rsplit(".", 1)[0].lower()
        if stem in _WINDOWS_RESERVED:
            raise InvalidInput(f"文件名为系统保留名称: {name}")

        if len(name.encode("utf-8")) > _MAX_FILENAME_BYTES:
            encoded = name.encode("utf-8")[:_MAX_FILENAME_BYTES]
            name = encoded.decode("utf-8", errors="ignore").rstrip(" .")
            if not name:
                raise InvalidInput(f"文件名过长: {raw}")

        return name


class StorageService:
    """目录配额策略：统计目录内文件总大小并判定上限。"""

    @staticmethod
    def dir_size_bytes(path: str) -> int:
        """返回目录下（非递归）所有文件的字节总数；目录不存在返回 0。"""
        total = 0
        if os.path.isdir(path):
            for entry in os.scandir(path):
                if entry.is_file():
                    total += entry.stat().st_size
        return total

    def check(self, path: str, max_mb: int, additional_bytes: int = 0) -> tuple[bool, float, float]:
        """检查目录是否超限。

        Args:
            path: 目标目录。
            max_mb: 上限（MB）；``<=0`` 表示不限制。
            additional_bytes: 额外待写入字节数（预检查）。

        Returns:
            tuple: ``(ok, current_mb, max_mb)``；未设限时 ``ok=True``。
        """
        if max_mb <= 0:
            return True, 0, max_mb
        total = self.dir_size_bytes(path) + additional_bytes
        current_mb = total / (1024 * 1024)
        return current_mb <= max_mb, round(current_mb, 2), max_mb

    def enforce(self, path: str, max_mb: int, additional_bytes: int = 0, *,
                label: str = "存储空间") -> None:
        """断言目录未超配额。

        Raises:
            AppError 413: 存储空间不足。
        """
        ok, current_mb, max_mb = self.check(path, max_mb, additional_bytes)
        if not ok:
            raise QuotaExceeded(
                f"{label}不足：已用 {current_mb}MB / 上限 {max_mb}MB，请清理后再上传"
            )

    def usage(self, path: str, max_mb: int) -> dict:
        """返回目录使用情况（读取失败时回退为默认值）。"""
        try:
            current_mb = round(self.dir_size_bytes(path) / (1024 * 1024), 2)
            return {
                "current_mb": current_mb,
                "max_mb": max_mb,
                "limit_enabled": max_mb > 0,
                "ok": max_mb <= 0 or current_mb <= max_mb,
            }
        except Exception:
            return {"current_mb": 0, "max_mb": max_mb, "limit_enabled": False, "ok": True}