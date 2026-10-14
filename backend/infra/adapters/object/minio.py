"""adapters.object.minio —— MinIO（S3 兼容）对象存储。

依赖 minio 包（未安装时实例化即报错）：pip install minio
"""

from __future__ import annotations

from collections.abc import Iterator


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

    def delete_keys(self, keys) -> None:
        """批量删除对象（MinIO remove_objects，每批 ≤1000）。"""
        from minio.deleteobjects import DeleteObject

        batch: list = []

        def _flush():
            if batch:
                try:
                    for _err in self._client.remove_objects(self.bucket, iter(batch)):
                        pass  # 消费错误流以触发删除
                except Exception:
                    pass
                batch.clear()

        try:
            for k in keys:
                batch.append(DeleteObject(_norm_key(k)))
                if len(batch) >= 1000:
                    _flush()
            _flush()
        except Exception:
            _flush()

    def list_keys(self, prefix: str = "") -> Iterator[str]:
        for obj in self._client.list_objects(self.bucket, prefix=prefix, recursive=True):
            yield obj.object_name

    def list_objects(self, prefix: str = "") -> list[tuple[str, int]]:
        """列出前缀下所有对象，返回 ``[(key, size), ...]``。"""
        out: list[tuple[str, int]] = []
        for obj in self._client.list_objects(self.bucket, prefix=prefix, recursive=True):
            out.append((obj.object_name, int(getattr(obj, "size", None) or 0)))
        return out


def _norm_key(key: str) -> str:
    return key.strip("/")
