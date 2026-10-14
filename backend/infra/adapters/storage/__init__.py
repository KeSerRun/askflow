"""adapters.storage —— 通用 SQLAlchemy 仓储 + 读缓存（不含业务模型）。

存储层与业务解耦：ORM 领域模型由各 ``modules/*/entity.py`` 继承 ``Base`` 定义，
本包只提供共享 ``Base``、按表名解析模型、通用仓储与缓存：
  - ``orm``  Base / model_for / row_to_dict / row_from_dict
  - ``SqlAlchemyRepo`` 基类（CRUD/事务），``SqliteRepo`` / ``MySQLRepo`` 子类
  - ``CachedRepo`` 读缓存（缓存纯 dict，命中重建实例）
"""

from .cached_repo import CachedRepo  # noqa: F401
from .mysql_repo import MySQLRepo  # noqa: F401
from .orm import Base, model_for, row_from_dict, row_to_dict  # noqa: F401
from .sql_base import SqlAlchemyRepo  # noqa: F401
from .sqlite_repo import SqliteRepo  # noqa: F401

__all__ = [
    "Base",
    "model_for",
    "row_to_dict",
    "row_from_dict",
    "SqlAlchemyRepo",
    "SqliteRepo",
    "MySQLRepo",
    "CachedRepo",
]
