"""modules.document.service —— 文档用例（保存 / 入库 / 清除 / 列出）。

对齐**真实管线**：
  1. 原始文件落盘到 ``{data_dir}/uploads/{user}/{filename}``
  2. 经 ``VectorStore.store_documents_from_dir`` 解析入库（解析产物 chunk_out/
     图片由解析器写到源文件同级目录，供下载/图片接口与完整性检查使用）
  3. 按来源/分区删除向量，并清理原文件与 chunk 产物

依赖：仅具体的 vector / history 适配器；``data_dir`` 由组合根注入。
"""

from __future__ import annotations

import glob
import os
import re
import shutil
from pathlib import Path
from typing import Optional

from infra.logger import logger

from core.errors import InvalidInput, NotFound, PermissionDenied
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

    def __init__(self, vector: object, history: object, storage: object, *,
                 data_dir: str, mineru_max_concurrency: int = 3):
        """初始化。

        Args:
            vector: 向量库适配器（提供 store_documents_from_dir / delete_by_* 等）。
            history: 历史服务（记录上传/删除事件）。
            storage: 存储配额服务（上传前校验，超限抛 AppError 413）。
            data_dir: 数据根目录（上传文件与 chunk 产物的落盘位置）。
            mineru_max_concurrency: 上传向量化的解析并发上限。
        """
        self._vector = vector
        self._history = history
        self._storage = storage
        self._data_dir = data_dir
        self._workers = max(1, int(mineru_max_concurrency or 1))

    # ── 路径 ──

    def upload_dir(self, user: str) -> str:
        """返回用户的暂存目录绝对路径。"""
        return os.path.join(self._data_dir, "uploads", user.lower())

    def _file_path(self, user: str, filename: str) -> str:
        return os.path.join(self.upload_dir(user), os.path.basename(filename))

    # ── 保存 ──

    def save_file(self, user: str, filename: str, data: bytes) -> dict:
        """保存单个原始文件（不解析）。

        Returns:
            dict: ``{"filename": str, "size": int}``。
        """
        name = os.path.basename(filename)
        save_path = self._file_path(user, name)
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        with open(save_path, "wb") as f:
            f.write(data)
        return {"filename": name, "size": len(data), "path": save_path}

    def save_uploads(self, user: str, files: list[tuple[str, bytes, str]], *,
                     session_id: Optional[str] = None, require_pdf: bool = True) -> list[dict]:
        """批量保存原始文件（含文件名清洗/PDF 校验），并记录一次上传事件。

        Args:
            user: 分区标识。
            files: ``[(原始文件名, data, content_type), ...]``。
            session_id: 关联会话（记录事件用）。
            require_pdf: 是否强制 PDF。

        Returns:
            list[dict]: 每个文件 ``{"filename", "size", "content_type"}``。
        """
        results = []
        for raw_name, data, content_type in files:
            name = self.sanitize_filename(raw_name)
            if require_pdf:
                self.ensure_pdf(name)
            info = self.save_file(user, name, data)
            results.append({"filename": name, "size": info["size"], "content_type": content_type})
        self.record_upload(session_id, [r["filename"] for r in results])
        return results

    def record_upload(self, session_id: Optional[str], filenames: list) -> None:
        """记录一次上传事件（可选）。"""
        if session_id and filenames:
            self._history.insert_session_event(session_id, "upload", list(filenames))

    # ── 清理 ──

    def purge(self, user: str, sources: Optional[list] = None) -> None:
        """清理原文件与其 chunk 产物。

        - ``sources=None``: 清空整个用户目录（含全部文件与 chunk_out/）
        - ``sources=[...]``: 仅清指定文件及其 ``chunk_out/{stem}/``
        """
        upload_dir = self.upload_dir(user)
        if not os.path.isdir(upload_dir):
            return

        if sources is None:
            shutil.rmtree(upload_dir, ignore_errors=True)
            return

        chunk_root = os.path.join(upload_dir, "chunk_out")
        for src in sources:
            name = os.path.basename(src)
            file_path = os.path.join(upload_dir, name)
            if os.path.isfile(file_path):
                os.remove(file_path)

            sub = os.path.join(chunk_root, os.path.splitext(name)[0])
            if os.path.isdir(sub):
                shutil.rmtree(sub, ignore_errors=True)

    # ── 入库 ──

    def forget_source(self, user: str, filename: str) -> None:
        """删除某来源的向量（不动文件）。"""
        self._vector.delete_by_sources([os.path.basename(filename)], partition=user.lower())

    def index_file(self, user: str, filename: str) -> None:
        """解析并入库已落盘的单个文件。"""
        self._vector.store_documents_from_dir(self._file_path(user, filename), partition=user.lower())

    def index_path(self, user: str, path: str) -> None:
        """解析并入库任意本地路径（目录或文件，路径安全由调用方校验）。"""
        self._vector.store_documents_from_dir(path, partition=user.lower())

    def add_documents(self, user: str, documents: list) -> None:
        """把已解析的文档分块入库。"""
        self._vector.add_documents(documents, partition=user.lower())

    def upload(self, user: str, filename: str, data: bytes) -> UploadResult:
        """保存 + 覆盖入库（先删同名向量与旧产物）。"""
        name = os.path.basename(filename)
        self.forget_source(user, name)
        self.purge(user, [name])
        self.save_file(user, name, data)
        self.index_file(user, name)
        return UploadResult(filename=name, sources=[name])

    # ── 列出 / 清除 ──

    def list_documents(self, user: str) -> list:
        """返回该用户已入库文档来源列表。"""
        return self._vector.get_sources_by_partition(user.lower())

    def clear_all(self, user: str, *, session_id: Optional[str] = None) -> None:
        """清除用户全部文档（向量 + 文件 + chunk 产物）。"""
        self._vector.delete_by_partition(partition=user.lower())
        self.purge(user, None)
        if session_id:
            self._history.insert_session_event(session_id, "delete_all", [])

    def clear_sources(self, user: str, sources: list, *, session_id: Optional[str] = None) -> None:
        """清除指定来源的文档（向量 + 文件 + chunk 产物）。"""
        self._vector.delete_by_sources(list(sources), partition=user.lower())
        self.purge(user, sources)
        if session_id:
            self._history.insert_session_event(session_id, "delete", list(sources))

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

    @staticmethod
    def ensure_pdf(filename: str) -> None:
        """断言文件为 PDF。

        Raises:
            AppError 400: 非 PDF。
        """
        if not filename.lower().endswith(".pdf"):
            raise InvalidInput(f"仅支持 PDF 文件，收到: {filename}")

    # ── 目录入库（含路径穿越防护） ──

    def add_from_path(self, user: str, rel_path: str) -> None:
        """把用户目录下的相对路径（目录/文件）解析入库。

        Raises:
            AppError 403: 路径穿越。
            AppError 400: 路径不存在。
        """
        upload_root = os.path.realpath(self.upload_dir(user))
        target = os.path.realpath(os.path.join(upload_root, rel_path))
        if target != upload_root and not target.startswith(upload_root + os.sep):
            raise PermissionDenied("forbidden")
        if not os.path.exists(target):
            raise NotFound("path not found")
        self.index_path(user, target)

    # ── 上传并向量化（进度事件流） ──

    def iter_upload_progress(self, user: str, session_id: Optional[str], files_data: list,
                             role: str = "user"):
        """上传 + 向量化的进度事件流（yield dict 事件；SSE 格式化由表示层负责）。

        Args:
            user: 分区标识。
            session_id: 关联会话（记录事件）。
            files_data: ``[(filename, content_bytes, content_type), ...]``。
            role: 用户角色（配额校验用）。

        Raises:
            AppError 413: 存储空间不足。
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        from infra.adapters.pdf.document_loader import process_documents_from_dir

        self._enforce_quota(user, role, files_data)

        prepared: list = []
        for raw_name, content, ct in files_data:
            name = self.sanitize_filename(raw_name)
            self.ensure_pdf(name)
            prepared.append((name, content, ct))

        results: list = []
        filenames: list = []
        error_count = 0

        saved: list[tuple[str, str]] = []
        for idx, (filename, content, _ct) in enumerate(prepared):
            yield {"status": "uploading", "text": "文档上传", "file": filename,
                   "progress": f"{idx + 1}/{len(prepared)}"}
            self.forget_source(user, filename)
            self.purge(user, [filename])
            info = self.save_file(user, filename, content)
            saved.append((filename, info["path"]))

        count = len(saved)
        text = f"正在处理 {count} 个文件..." if count > 1 else "正在处理文件..."
        yield {"status": "info", "text": text}

        def _process_one(fn: str, sp: str):
            events = [{"status": "parsing", "text": "文档解析", "file": fn}]
            documents = process_documents_from_dir(sp)
            if not documents:
                events.append({"status": "error", "text": "解析失败", "file": fn})
                return events, None
            events.append({"status": "embedding", "text": "词嵌入", "file": fn})
            try:
                self.add_documents(user, documents)
            except Exception as e:
                logger.error(f"文档嵌入入库失败 ({fn}): {e}")
                events.append({"status": "error", "text": f"嵌入失败: {e}", "file": fn})
                return events, None
            events.append({"status": "done", "text": "处理完成", "file": fn})
            return events, fn

        with ThreadPoolExecutor(max_workers=self._workers) as pool:
            futures = {pool.submit(_process_one, fn, sp): fn for fn, sp in saved}
            for future in as_completed(futures):
                events, fn = future.result()
                for e in events:
                    yield e
                if fn:
                    results.append({"filename": fn})
                    filenames.append(fn)
                else:
                    error_count += 1

        self.record_upload(session_id, filenames)

        if error_count > 0 and not results:
            yield {"status": "done", "text": "所有文件均处理失败", "files": results}
        elif error_count > 0:
            yield {"status": "done", "text": f"入库完成，{error_count} 个文件失败", "files": results}
        else:
            yield {"status": "done", "text": "入库成功", "files": results}

    def upload_and_index(self, user: str, files_data: list, *,
                         role: str = "user", session_id: Optional[str] = None) -> list[dict]:
        """上传并向量化一批文件（非流式）：先校验配额，再入库。

        Args:
            user: 分区标识。
            files_data: ``[(原始文件名, content_bytes, content_type), ...]``。
            role: 用户角色（配额校验用）。
            session_id: 关联会话（记录一次上传事件）。

        Raises:
            AppError 413: 存储空间不足。
        """
        self._enforce_quota(user, role, files_data)
        results = []
        for raw_name, content, content_type in files_data:
            name = self.sanitize_filename(raw_name)
            self.ensure_pdf(name)
            self.upload(user, name, content)
            results.append({"filename": name, "size": len(content), "content_type": content_type})
        self.record_upload(session_id, [r["filename"] for r in results])
        return results

    def _enforce_quota(self, user: str, role: str, files_data: list) -> None:
        """按待写入字节数校验存储配额。

        Raises:
            AppError 413: 存储空间不足。
        """
        total_bytes = sum(len(content) for _, content, _ in files_data)
        self._storage.enforce(user, role, total_bytes)

    # ── 文件 / 图片解析（供下载与图片接口） ──

    def resolve_user_file(self, user: str, filename: str) -> str:
        """解析用户上传文件的真实路径（路径穿越/存在性校验）。

        Raises:
            AppError 403: 路径穿越。
            AppError 404: 文件不存在。
        """
        upload_root = os.path.realpath(self.upload_dir(user))
        target = os.path.realpath(os.path.join(upload_root, filename))
        if target != upload_root and not target.startswith(upload_root + os.sep):
            raise PermissionDenied("forbidden")
        if not os.path.isfile(target):
            raise NotFound("file not found")
        return target

    def find_image(self, doc_stem: str, img_name: str) -> Optional[str]:
        """按 doc_stem 定位 MinerU 解析图片（逐级放宽匹配），返回绝对路径或 None。"""
        data = Path(self._data_dir)
        base_dir = data / "uploads" / "*" / "chunk_out" / doc_stem

        candidates = glob.glob(str(base_dir / img_name))
        if not candidates:
            candidates = sorted(glob.glob(str(base_dir / f"{img_name}*")))

        if not candidates and "." in doc_stem:
            stem_clean = doc_stem.rsplit(".", 1)[0]
            base_dir2 = data / "uploads" / "*" / "chunk_out" / stem_clean
            candidates = sorted(glob.glob(str(base_dir2 / f"{img_name}*")))

        if not candidates:
            base_dir_fuzzy = data / "uploads" / "*" / "chunk_out" / f"{doc_stem}*"
            candidates = sorted(glob.glob(str(base_dir_fuzzy / img_name)))
            if not candidates:
                candidates = sorted(glob.glob(str(base_dir_fuzzy / f"{img_name}*")))
            if not candidates and "." in doc_stem:
                stem_clean = doc_stem.rsplit(".", 1)[0]
                base_dir_fuzzy2 = data / "uploads" / "*" / "chunk_out" / f"{stem_clean}*"
                candidates = sorted(glob.glob(str(base_dir_fuzzy2 / img_name)))
                if not candidates:
                    candidates = sorted(glob.glob(str(base_dir_fuzzy2 / f"{img_name}*")))

        if not candidates and "/" in img_name:
            prefix = img_name.rsplit("/", 1)[0]
            candidates = sorted(glob.glob(str(base_dir / prefix / "*")))
            if not candidates:
                base_dir_fuzzy = data / "uploads" / "*" / "chunk_out" / f"{doc_stem}*"
                candidates = sorted(glob.glob(str(base_dir_fuzzy / prefix / "*")))
            if not candidates and "." in doc_stem:
                stem_clean = doc_stem.rsplit(".", 1)[0]
                base_dir_extless = data / "uploads" / "*" / "chunk_out" / stem_clean
                candidates = sorted(glob.glob(str(base_dir_extless / prefix / "*")))
                if not candidates:
                    base_dir_fuzzy2 = data / "uploads" / "*" / "chunk_out" / f"{stem_clean}*"
                    candidates = sorted(glob.glob(str(base_dir_fuzzy2 / prefix / "*")))

        if not candidates:
            raise NotFound("image not found")
        return str(Path(candidates[0]).resolve())

    def find_image_global(self, img_name: str) -> Optional[str]:
        """全局搜索 MinerU 图片（仅有图片 hash 时使用），返回绝对路径或 None。"""
        img_name = img_name.rstrip("/")
        if img_name.startswith("images/"):
            img_name = img_name[7:]

        data = Path(self._data_dir)
        pattern = str(data / "uploads" / "*" / "chunk_out" / "*" / "images" / img_name)
        candidates = sorted(glob.glob(pattern))
        if not candidates:
            name_wo_ext = img_name.rsplit(".", 1)[0] if "." in img_name else img_name
            pattern = str(data / "uploads" / "*" / "chunk_out" / "*" / "images" / f"{name_wo_ext}*")
            candidates = sorted(glob.glob(pattern))

        if not candidates:
            raise NotFound("image not found")
        return str(Path(candidates[0]).resolve())