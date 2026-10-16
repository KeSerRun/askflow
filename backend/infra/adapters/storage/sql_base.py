"""adapters.storage.sql_base —— SQLAlchemy 通用仓储基类（CRUD + 事务）。

具体的数据库实现（``SqliteRepo`` / ``MySQLRepo`` / 未来其它）继承本类，
只需实现 ``_create_engine``（引擎与连接参数）；CRUD、事务、会话策略完全复用。

读写直接使用 ORM 实例（领域模型即各 ``modules/*/entity.py`` 的 ORM 类）。

统一异常处理：``_guarded`` 装饰器收拢 "捕获 SQL 异常 + 打日志 + 返回默认值"，
方法体里不再写 try/except。
"""

from __future__ import annotations

from contextlib import contextmanager, nullcontext
from functools import wraps

from sqlalchemy import delete as sa_delete
from sqlalchemy import func, or_, select
from sqlalchemy import update as sa_update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from infra.util.logger import logger

from .orm import Base, model_for


def _guarded(default, *, catch_integrity: bool = False):
    """统一异常守卫：SQL 失败 → 记日志（方法+集合）+ 返回默认值。

    Args:
        default: 失败时的返回值（如 None / [] / 0 / False）。
        catch_integrity: 唯一键冲突也视为"业务结果"而非告警（insert 用）。
    """

    def deco(fn):
        @wraps(fn)
        def wrapper(self, collection, *args, **kwargs):
            try:
                return fn(self, collection, *args, **kwargs)
            except IntegrityError as e:
                if catch_integrity:
                    logger.debug(f"[{type(self).__name__}] {fn.__name__} {collection} 唯一键冲突: {e}")
                else:
                    logger.warning(f"[{type(self).__name__}] {fn.__name__} {collection} 失败: {e}")
                return default
            except SQLAlchemyError as e:
                logger.warning(f"[{type(self).__name__}] {fn.__name__} {collection} 失败: {e}")
                return default
        return wrapper

    return deco


class _OwnSession:
    """独立调用使用的会话包装：正常退出自动 commit，异常自动 rollback。"""

    def __init__(self, session):
        self._session = session

    def __enter__(self):
        return self._session

    def __exit__(self, exc_type, exc, _tb):
        try:
            if exc_type is None:
                self._session.commit()
            else:
                self._session.rollback()
        finally:
            self._session.close()


class SqlAlchemyRepo:
    """基于 SQLAlchemy 的通用对象仓储基类（集合→表、ORM 实例读写）。

    子类必须实现 ``_create_engine(url)`` 返回一个 SQLAlchemy Engine。

    事务：``transaction()`` 复用同一 session；各 CRUD 方法接受可选 ``session``。
    提交策略收敛在一处：独立调用由 ``_OwnSession`` 退出时自动 commit/rollback；
    事务内不提交，由 ``transaction`` 统一提交/回滚。
    """

    def __init__(self, url: str):
        self._engine = self._create_engine(url)
        self._Session = sessionmaker(bind=self._engine, expire_on_commit=False, future=True)
        Base.metadata.create_all(self._engine, checkfirst=True)

    def _create_engine(self, url: str):  # pragma: no cover - 抽象
        """由子类实现：按各自数据库创建 Engine。"""
        raise NotImplementedError

    def _session_scope(self, session):
        """返回会话作用域：复用外部会话（事务内，不提交）或独立会话（退出自动提交）。"""
        if session is not None:
            return nullcontext(session)
        return _OwnSession(self._Session())

    # ── 事务 ──

    @contextmanager
    def transaction(self):
        """开启一个显式事务：复用同一 session，正常退出提交、异常回滚。

        用法::

            with repo.transaction() as s:
                repo.insert("users", User(...), session=s)
                repo.update("users", uid, {...}, session=s)

        注意：事务内若某个 CRUD 方法吞掉错误（返回 None/False），仍需由调用方
        检查返回值并抛异常，事务才会回滚；否则已成功的操作会被一起提交。
        """
        with self._Session() as s:
            try:
                yield s
                s.commit()
            except Exception:
                s.rollback()
                raise

    # ── 通用 CRUD（异常由 _guarded 统一处理） ──

    @_guarded(None, catch_integrity=True)
    def insert(self, collection: str, entity, session=None):
        """插入 ORM 实例（也兼容 dict），返回新 id；唯一键冲突/失败返回 None。"""
        model = model_for(collection)
        row = entity if isinstance(entity, Base) else model(
            **{k: v for k, v in entity.items() if k != "id"})
        with self._session_scope(session) as s:
            s.add(row)
            s.flush()  # 让自增 id 先落位；独立调用退出后由 _OwnSession 提交
            return row.id

    @_guarded(None)
    def get(self, collection: str, doc_id, session=None):
        """按 id 读取，返回 ORM 实例或 None。"""
        model = model_for(collection)
        with self._session_scope(session) as s:
            return s.get(model, doc_id)

    @_guarded([])
    def find(self, collection: str, where: dict | None = None, *,
             order_by: str | None = None, offset: int = 0, limit: int | None = None,
             session=None) -> list:
        """按条件查询，返回 ORM 实例列表。

        ``order_by`` 支持 ``"-id"`` 形式（前缀 ``-`` 表示降序）。
        """
        model = model_for(collection)
        with self._session_scope(session) as s:
            stmt = select(model)
            criteria = self._criteria(model, where)
            if criteria:
                stmt = stmt.where(*criteria)
            if order_by:
                desc = order_by.startswith("-")
                col = getattr(model, order_by.lstrip("-"))
                stmt = stmt.order_by(col.desc() if desc else col.asc())
            stmt = stmt.offset(offset or None).limit(limit)
            return list(s.execute(stmt).scalars().all())

    @_guarded(0)
    def count(self, collection: str, where: dict | None = None, session=None) -> int:
        model = model_for(collection)
        with self._session_scope(session) as s:
            stmt = select(func.count()).select_from(model)
            criteria = self._criteria(model, where)
            if criteria:
                stmt = stmt.where(*criteria)
            return s.execute(stmt).scalar() or 0

    @_guarded(False)
    def update(self, collection: str, doc_id, fields: dict, session=None) -> bool:
        """按 id 更新字段，返回是否实际改动。"""
        model = model_for(collection)
        with self._session_scope(session) as s:
            result = s.execute(
                sa_update(model).where(model.id == doc_id).values(**fields)
                    .execution_options(synchronize_session=False)
            )
            return (result.rowcount or 0) > 0

    @_guarded(0)
    def update_where(self, collection: str, where: dict, fields: dict, session=None) -> int:
        """按条件批量更新，返回受影响条数（单条 UPDATE 语句）。"""
        model = model_for(collection)
        with self._session_scope(session) as s:
            stmt = sa_update(model).values(**fields)
            criteria = self._criteria(model, where)
            if criteria:
                stmt = stmt.where(*criteria)
            result = s.execute(stmt.execution_options(synchronize_session=False))
            return result.rowcount or 0

    @_guarded(False)
    def delete(self, collection: str, doc_id, session=None) -> bool:
        """按 id 删除，返回是否实际删除。"""
        model = model_for(collection)
        with self._session_scope(session) as s:
            result = s.execute(
                sa_delete(model).where(model.id == doc_id)
                    .execution_options(synchronize_session=False)
            )
            return (result.rowcount or 0) > 0

    @_guarded(0)
    def delete_where(self, collection: str, where: dict, session=None) -> int:
        """按条件批量删除，返回删除条数（单条 DELETE 语句）。"""
        model = model_for(collection)
        with self._session_scope(session) as s:
            stmt = sa_delete(model)
            criteria = self._criteria(model, where)
            if criteria:
                stmt = stmt.where(*criteria)
            result = s.execute(stmt.execution_options(synchronize_session=False))
            return result.rowcount or 0

    # ── 内部 ──

    @classmethod
    def _criteria(cls, model, where: dict | None) -> list:
        """把 ``where`` 字典转成 SQLAlchemy 条件列表（各项之间为 AND）。

        支持键修饰符（见 :meth:`_condition`），以及特殊键 ``__or__``：
        其值为「条件字典列表」，组内各条件先 OR、再与整体 AND。
        """
        where = where or {}
        criteria = []
        for key, value in where.items():
            if key == "__or__":
                or_criteria = []
                for group in value or []:
                    or_criteria.extend(cls._criteria(model, group))
                if or_criteria:
                    criteria.append(or_(*or_criteria))
                continue
            criteria.append(cls._condition(model, key, value))
        return criteria

    @staticmethod
    def _condition(model, key: str, value):
        """单个字段条件。

        支持：``field``（等值）/ ``field__ne`` / ``field__ieq``（大小写不敏感等值）/
        ``field__contains``（LIKE）/ ``field__icontains``（ILIKE）/ ``field__in``。
        """
        if key.endswith("__ieq"):
            # 大小写不敏感等值：LOWER(col) = LOWER(:value)
            return func.lower(getattr(model, key[:-5])) == str(value).lower()
        if key.endswith("__ne"):
            return getattr(model, key[:-4]) != value
        if key.endswith("__icontains"):
            return getattr(model, key[:-11]).ilike(f"%{value}%")
        if key.endswith("__contains"):
            return getattr(model, key[:-10]).like(f"%{value}%")
        if key.endswith("__in"):
            return getattr(model, key[:-4]).in_(list(value))
        return getattr(model, key) == value
