"""infra.adapters.storage.orm —— ORM 基类与模型解析（存储层，不含业务模型）。

各业务模块在自己的 ``entity.py`` 里继承 ``Base`` 定义 ORM 领域模型；
本文件只提供共享 ``Base``、按表名解析模型、以及通用 dict 转换，**不依赖任何业务模块**。
"""

from __future__ import annotations

from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


def model_for(collection: str):
    """按表名（=集合名）从 Base 注册表解析 ORM 模型类（存储层不硬编码业务模型）。"""
    for mapper in Base.registry.mappers:
        table = getattr(mapper, "local_table", None)
        if table is not None and table.name == collection:
            return mapper.class_
    raise KeyError(f"未知集合（未注册的 ORM 模型）: {collection}")


def row_to_dict(obj) -> dict:
    """ORM 行 → 纯 dict（供缓存序列化/展示层）。"""
    return {attr.key: getattr(obj, attr.key)
            for attr in sa_inspect(type(obj)).mapper.column_attrs}


def row_from_dict(collection: str, d: dict):
    """纯 dict → ORM 实例（缓存命中时重建）。"""
    return model_for(collection)(**d)
