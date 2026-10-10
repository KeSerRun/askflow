"""adapters.object —— ObjectStore 实现。"""

from .local import LocalObjectStore  # noqa: F401
from .minio import MinioObjectStore  # noqa: F401

__all__ = ["LocalObjectStore", "MinioObjectStore"]