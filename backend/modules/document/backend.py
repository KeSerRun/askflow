"""modules.document.backend —— 文档文件存储后端（仅对象存储）。

MinIO（默认桶 ``rag-files``）为唯一文件存储，**不读写项目的 ``data`` 目录**。
对象键与项目相对路径 **1:1**：

- 系统文档：``uploads/{partition}/{filename}``、``uploads/{partition}/chunk_out/{stem}/...``
- 会话附件：``sessions/{user}/{session_id}/{filename}``、``sessions/{user}/{session_id}/chunk_out/{stem}/...``

MinerU 解析 / 结果响应等需要真实文件路径的场景，由 ``local_materialize`` 把对象
**物化到系统临时目录**（非项目目录），解析产物再通过 ``upload_subtree`` 上传回对象存储，
随后清理临时文件。

``object_store`` 为 None（MinIO 不可用）时存取直接不可用（返回空/抛错），不做任何本地回退。
对象存储适配器需提供：``put_bytes / get_bytes / delete / list_objects / list_keys``；
可选提供 ``local_path(key)``（本地型实现可免物化直接返回路径）。
"""

from __future__ import annotations

import os
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Optional


def _norm_key(rel: str) -> str:
    """规范化对象键（去首尾斜杠/`.`/`..`，统一 `/` 分隔）。"""
    rel = (rel or "").strip().replace("\\", "/")
    parts = [p for p in rel.split("/") if p not in ("", ".", "..")]
    return "/".join(parts)


def match_img_key(key: str, img_name: str) -> bool:
    """判断对象键是否匹配引用的图片名（支持 ``images/`` 前缀、子目录与模糊名）。

    Args:
        key: 对象键（形如 ``uploads/__system__/chunk_out/{stem}/images/img_0001.jpg``）。
        img_name: 引用名（可为 ``img_0001.jpg`` 或 ``images/img_0001.jpg``）。

    Returns:
        命中返回 True。
    """
    if "images/" not in key:
        return False
    tail = key.split("images/", 1)[1]
    if not tail:
        return False
    target = (img_name or "").lstrip("/")
    if target.startswith("images/"):
        target = target[len("images/"):]
    base = tail.split("/")[-1]
    tbase = target.rsplit("/", 1)[-1]
    return base == tbase or base.startswith(tbase + ".") or base.startswith(tbase)


class FileStore:
    """文档文件存储：仅对象存储的读写面。"""

    def __init__(self, object_store: Optional[object] = None, tmp_root: str = ""):
        """初始化。

        Args:
            object_store: 对象存储适配器；None 表示 MinIO 不可用（读写被禁用）。
            tmp_root: 临时物化根目录；留空用系统临时目录（``{tmp}/askflow-files``）。
        """
        self.os = object_store
        self._tmp_root = tmp_root or os.path.join(tempfile.gettempdir(), "askflow-files")
        self._sandbox = os.path.join(self._tmp_root, uuid.uuid4().hex[:8])
        os.makedirs(self._sandbox, exist_ok=True)
        # 已物化到临时沙盒的对象：key -> 本地路径
        self._materialized: dict[str, str] = {}

    # ── 基础 ──

    @property
    def enabled(self) -> bool:
        """对象存储是否可用。"""
        return self.os is not None

    def _require(self) -> None:
        if self.os is None:
            raise RuntimeError("对象存储未启用（MinIO 不可用），文件读写被禁用")

    @staticmethod
    def _key(rel: str) -> str:
        return _norm_key(rel)

    # ── 写 ──

    def put(self, rel: str, data: bytes, content_type: str = "") -> None:
        self._require()
        self.os.put_bytes(self._key(rel), data, content_type=content_type)

    # ── 读 ──

    def get_bytes(self, rel: str) -> Optional[bytes]:
        if self.os is None:
            return None
        return self.os.get_bytes(self._key(rel))

    def read_text(self, rel: str) -> Optional[str]:
        data = self.get_bytes(rel)
        if data is None:
            return None
        try:
            return data.decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            return None

    # ── 列表 / 统计 ──

    def list(self, prefix: str) -> list[dict]:
        """列出 prefix 下的**直接文件**（非递归）：``[{name, size}, ...]`` 按名排序。"""
        if self.os is None:
            return []
        prefix = self._key(prefix)
        prefix_plus = prefix + "/" if prefix else ""
        out: dict[str, int] = {}
        try:
            for key, size in self.os.list_objects(prefix_plus):
                tail = key[len(prefix_plus):] if prefix_plus else key
                if not tail or "/" in tail:
                    continue  # 嵌套产物（chunk_out 等）不属于直接文件
                out[tail] = max(out.get(tail, 0), size)
        except Exception:  # noqa: BLE001
            pass
        return [{"name": k, "size": v} for k, v in sorted(out.items())]

    def list_all(self, prefix: str) -> list[dict]:
        """列出 prefix 下全部对象（递归）：``[{name, size}, ...]``。"""
        if self.os is None:
            return []
        prefix = self._key(prefix)
        prefix_plus = prefix + "/" if prefix else ""
        out: dict[str, int] = {}
        try:
            for key, size in self.os.list_objects(prefix_plus):
                out[key] = max(out.get(key, 0), size)
        except Exception:  # noqa: BLE001
            pass
        return [{"name": k, "size": v} for k, v in sorted(out.items())]

    def size_bytes(self, prefix: str) -> int:
        """prefix 下所有对象的字节总数。"""
        return sum(item["size"] for item in self.list_all(prefix))

    # ── 删除 ──

    def delete(self, rel: str) -> None:
        if self.os is None:
            return
        self.os.delete(self._key(rel))

    def delete_prefix(self, prefix: str) -> None:
        if self.os is None:
            return
        prefix = self._key(prefix)
        prefix_plus = prefix + "/" if prefix else prefix
        try:
            keys = [key for key, _ in self.os.list_objects(prefix_plus)]
        except Exception:  # noqa: BLE001
            keys = []
        if keys:
            self.os.delete_keys(keys)

    # ── 临时物化（对象代理：MinerU 解析需要真实文件路径时使用） ──

    def local_materialize(self, rel: str) -> Optional[str]:
        """返回对象对应的真实本地路径。

        - 适配器提供 ``local_path(key)``（本地型实现）时直接返回其路径；
        - 否则下载对象到**系统临时沙盒**并缓存；
        - 对象不存在返回 None。
        """
        self._require()
        key = self._key(rel)

        lp = getattr(self.os, "local_path", None)
        if lp is not None:
            p = lp(key) if callable(lp) else None
            if p and os.path.isfile(p):
                return p
            return None

        cached = self._materialized.get(key)
        if cached and os.path.isfile(cached):
            return cached

        data = self.os.get_bytes(key)
        if data is None:
            return None
        dest = Path(self._sandbox) / key
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        self._materialized[key] = str(dest)
        return str(dest)

    def cleanup_materialized(self, rel: str) -> None:
        """清理 rel 物化出的临时文件与其 MinerU 产物（chunk_out/{stem}/）。"""
        path = self._materialized.pop(self._key(rel), None)
        if not path:
            return
        p = Path(path)
        try:
            if p.is_file():
                p.unlink()
        except OSError:
            pass
        try:
            shutil.rmtree(p.parent / "chunk_out" / p.stem, ignore_errors=True)
        except OSError:
            pass

    # ── 子树上传：把本地产物目录整体写入对象存储 ──

    def upload_subtree(self, local_dir: str, key_prefix: str) -> None:
        """把 local_dir 下所有文件递归写入 ``key_prefix/{相对路径}``。"""
        self._require()
        root = Path(local_dir)
        if not root.is_dir():
            return
        prefix = self._key(key_prefix)
        for p in root.rglob("*"):
            if p.is_file():
                rel = p.relative_to(root).as_posix()
                self.os.put_bytes(f"{prefix}/{rel}", p.read_bytes())