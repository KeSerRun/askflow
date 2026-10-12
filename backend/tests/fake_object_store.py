"""fake_object_store —— 本地目录版对象存储（测试替身）。

实现接口与 ``MinioObjectStore`` 一致（``put_bytes / get_bytes / exists / delete /
list_keys / list_objects``），另提供 ``local_path(key)``：对象直接落在 base 目录下
（key 即相对路径），FileStore.local_materialize 走 local_path 返回真实路径，
从而让 MinerU/FakeVector 的产物落在可断言的位置（与早期本地磁盘行为一致）。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator


class LocalDirObjectStore:
    """把对象键映射为 ``base_dir/{key}`` 目录下文件的本地实现。"""

    def __init__(self, base_dir: str):
        """初始化。

        Args:
            base_dir: 对象落盘根目录（键的相对路径即其下路径）。
        """
        self.base = os.path.abspath(base_dir or os.getcwd())

    def _path(self, key: str) -> Path:
        key = (key or "").strip("/").replace("/", os.sep)
        return Path(self.base, key) if key else Path(self.base)

    def put_bytes(self, key: str, data: bytes, content_type: str = "") -> None:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def get_bytes(self, key: str) -> bytes | None:
        p = self._path(key)
        return p.read_bytes() if p.is_file() else None

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def delete(self, key: str) -> bool:
        p = self._path(key)
        if p.is_file():
            p.unlink()
            return True
        return False

    def delete_keys(self, keys) -> None:
        for k in keys:
            self.delete(k)

    def list_keys(self, prefix: str = "") -> Iterator[str]:
        root = self._path(prefix)
        if root.is_dir():
            for p in root.rglob("*"):
                if p.is_file():
                    yield p.relative_to(Path(self.base)).as_posix()

    def list_objects(self, prefix: str = "") -> list[tuple[str, int]]:
        return [(k, p.stat().st_size) for k, p in
                ((k, self._path(k)) for k in self.list_keys(prefix)) if p.is_file()]

    def local_path(self, key: str) -> str | None:
        p = self._path(key)
        return str(p) if p.is_file() else None