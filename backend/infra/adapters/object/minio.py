"""adapters.object.minio —— MinIO（S3 兼容）对象存储。

依赖 minio 包（未安装时实例化即报错）：pip install minio
"""

from __future__ import annotations

from typing import Iterator



class MinioObjectStore:
    """基于 MinIO 的对象存储实现。"""

    def __init__(
        self,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket: str = "rag-files",
        secure: bool = False,
    ):
        """初始化。

        Args:
            endpoint: MinIO 地址（host:port）。
            access_key / secret_key: 凭证。
            bucket: 桶名（需已存在，可用 minio-init 自动创建）。
            secure: 是否 HTTPS。

        Raises:
            ImportError: 未安装 minio 依赖。
        """
        try:
            from minio import Minio  # 延迟导入
        except ImportError as e:  # pragma: no cover
            raise ImportError("MinIO 适配器需要安装 minio 依赖: pip install minio") from e

        self.bucket = bucket
        self._client = Minio(
            endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
        )

    def put_bytes(self, key: str, data: bytes, content_type: str = "") -> None:
        from io import BytesIO

        self._client.put_object(
            self.bucket,
            _norm_key(key),
            BytesIO(data),
            length=len(data),
            content_type=content_type or "application/octet-stream",
        )

    def get_bytes(self, key: str) -> bytes | None:
        try:
            resp = self._client.get_object(self.bucket, _norm_key(key))
        except Exception:
            return None
        try:
            return resp.read()
        finally:
            resp.close()
            resp.release_conn()

    def exists(self, key: str) -> bool:
        try:
            self._client.stat_object(self.bucket, _norm_key(key))
            return True
        except Exception:
            return False

    def delete(self, key: str) -> bool:
        try:
            self._client.remove_object(self.bucket, _norm_key(key))
            return True
        except Exception:
            return False

    def list_keys(self, prefix: str = "") -> Iterator[str]:
        for obj in self._client.list_objects(self.bucket, prefix=prefix, recursive=True):
            yield obj.object_name

    def copy(self, src_key: str, dst_key: str) -> None:
        self._client.copy_object(
            self.bucket, _norm_key(dst_key),
            f"{self.bucket}/{_norm_key(src_key)}",
        )

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


def _norm_key(key: str) -> str:
    return key.strip("/")