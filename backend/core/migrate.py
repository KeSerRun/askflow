"""core.migrate —— 极简数据迁移（幂等，供组合根启动时调用）。

当前需求：把用户身份从 username 收敛到 user_id（users.id）。
- ``sessions`` / ``request_logs`` / ``refresh_tokens`` 补 ``user_id`` 列；
- 按 ``username`` 回填 ``user_id = users.id``（大小写不敏感）。
"""

from __future__ import annotations

from sqlalchemy import inspect as _sa_inspect
from sqlalchemy import text as _sa_text


def _raw_engine(repo):
    """穿透缓存包装取底层 SQL 引擎。"""
    raw = getattr(repo, "_repo", repo)
    return raw._engine


def purge_deprecated_tools(repo) -> None:
    """删除已从代码中移除的内建工具行（``agent_tools``，幂等）。"""
    try:
        engine = _raw_engine(repo)
    except Exception:
        return
    try:
        with engine.begin() as conn:
            conn.execute(_sa_text(
                "DELETE FROM agent_tools WHERE name IN ('read_document_titles', 'read_section', "
                "'list_documents', 'read_full_document')"
            ))
    except Exception:
        return


def ensure_user_identity(repo) -> None:
    """确保三张关联表具备 ``user_id`` 并回填存量数据（幂等，单项失败不影响其余）。"""
    try:
        engine = _raw_engine(repo)
    except Exception:
        return

    def _has(table: str, col: str) -> bool:
        return col in {c["name"] for c in _sa_inspect(engine).get_columns(table)}

    with engine.begin() as conn:
        for table in ("sessions", "request_logs", "refresh_tokens"):
            if not _has(table, "user_id"):
                try:
                    conn.execute(_sa_text(f"ALTER TABLE {table} ADD COLUMN user_id INTEGER"))
                except Exception:
                    continue
            try:
                # 按 username 回填（users.username 当前为严格区分大小写的原值；回填用不区分匹配同存量小写）
                conn.execute(_sa_text(
                    f"UPDATE {table} SET user_id = ("
                    "SELECT id FROM users WHERE LOWER(users.username) = LOWER(" + table + ".username)"
                    " LIMIT 1) WHERE user_id IS NULL"
                ))
            except Exception:
                continue
