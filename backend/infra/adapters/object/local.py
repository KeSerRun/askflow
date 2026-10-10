"""adapters.object.local —— 本地磁盘对象存储。

行为对齐 ObjectStore 契约；key 中禁止路径穿越（防 "../" 逃逸到仓库外）。
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Iterator



def _safe_rel(key: str) -> str:
    """校验并规整 key：去首尾斜杠、禁绝对路径、禁上一级逃逸。"""
    key = key.replace("\\", "/").strip("/")
    if not key:
        raise ValueError("empty object key")
    parts = [p for p in key.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        raise ValueError(f"unsafe object key: {key!r}")
    return "/".join(parts)


class LocalObjectStore:
    """基于本地目录的对象存储实现。"""

    def __init__(self, base_dir: str | Path):
        """初始化。

        Args:
            base_dir: 本地根目录（如 conf.storage_data_dir）。
        """
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        return self.base_dir / _safe_rel(key)

    def put_bytes(self, key: str, data: bytes, content_type: str = "") -> None:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def get_bytes(self, key: str) -> bytes | None:
        p = self._path(key)
        if not p.is_file():
            return None
        return p.read_bytes()

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def delete(self, key: str) -> bool:
        p = self._path(key)
        if not p.exists():
            return False
        if p.is_dir():
            shutil.rmtree(p)
        else:
            p.unlink()
        return True

    def list_keys(self, prefix: str = "") -> Iterator[str]:
        # 校验必须发生在返回生成器之前（生成器是惰性的）
        _safe_rel(prefix) if prefix else None
        root = self.base_dir / prefix if prefix else self.base_dir

        def _walk() -> Iterator[str]:
            if not root.exists():
                return
            for p in root.rglob("*"):
                if p.is_file():
                    yield p.relative_to(self.base_dir).as_posix()

        return _walk()

    def copy(self, src_key: str, dst_key: str) -> None:
        data = self.get_bytes(src_key)
        if data is None:
            raise FileNotFoundError(f"src key not found: {src_key}")
        self.put_bytes(dst_key, data)

    # ── 便捷方法 ──

    def put_file(self, key: str, local_path: str) -> None:
        """从本地文件写入对象。"""
        with open(local_path, "rb") as f:
            self.put_bytes(key, f.read())

    def get_to_file(self, key: str, local_path: str) -> bool:
        """将对象写到本地文件；不存在返回 False。"""
        data = self.get_bytes(key)
        if data is None:
            return False
        with open(local_path, "wb") as f:
            f.write(data)
        return True