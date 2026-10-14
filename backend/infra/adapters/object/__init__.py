"""adapters.object —— ObjectStore 实现。"""

from .minio import MinioObjectStore  # noqa: F401

__all__ = ["MinioObjectStore"]
