"""core.pagination —— 通用分页。

- ``paginate``：把**已加载**的可迭代对象切片（用于内存列表 / 目录扫描等本就是全量的场景）；
- ``paginate_query``：**仓储层分页**（``count`` + ``find`` 的 ``LIMIT/OFFSET``），不把全表读进内存。

两者返回同一信封：``{"total", "page", "page_size", <key>}``；
约定 ``page_size <= 0`` 表示「全部」。
"""

from __future__ import annotations


def paginate(items, page: int = 1, page_size: int = 0, *, key: str = "items") -> dict:
    """把可迭代对象切片为统一分页响应。

    Args:
        items: 可迭代对象（列表 / 元组等）。
        page: 页码，从 1 开始。
        page_size: 每页大小；``<= 0`` 表示全部。
        key: 列表字段名（如 ``documents`` / ``sessions`` / ``issues``）。

    Returns:
        ``{"total": int, "page": int, "page_size": int, key: list}``。
    """
    items = list(items)
    total = len(items)
    try:
        size = int(page_size or 0)
    except (TypeError, ValueError):
        size = 0
    if size <= 0:
        return {"total": total, "page": 1, "page_size": total, key: items}
    try:
        page = max(1, int(page or 1))
    except (TypeError, ValueError):
        page = 1
    start = (page - 1) * size
    return {"total": total, "page": page, "page_size": size, key: items[start:start + size]}


def paginate_query(repo, collection, *, where: dict | None = None, order_by: str | None = None,
                   page: int = 1, page_size: int = 0, key: str = "items", serialize=None) -> dict:
    """**仓储层**分页：``count(where)`` + ``find(where, order_by, offset, limit)``。

    与 :func:`paginate` 返回同一信封 ``{"total", "page", "page_size", <key>}``；
    分页在 SQL 层完成（``LIMIT/OFFSET``），不会把全表读进内存。

    Args:
        repo: 通用仓储（提供 ``find`` / ``count``）。
        collection: 集合名（如 ``"users"`` / ``"app_logs"``）。
        where: 条件字典（支持 ``__contains`` / ``__icontains`` / ``__or__`` 等，见仓储层）。
        order_by: 排序字段；``"-id"`` 表示降序。
        page: 页码，从 1 开始。
        page_size: 每页大小；``<= 0`` 表示全部（此时不做 LIMIT）。
        key: 返回里列表字段名。
        serialize: 把 ORM 行映射为可序列化对象；缺省原样返回。

    Returns:
        ``{"total": int, "page": int, "page_size": int, key: list}``。
    """
    try:
        size = int(page_size or 0)
    except (TypeError, ValueError):
        size = 0
    to_json = serialize or (lambda row: row)

    if size <= 0:  # 全部：不 LIMIT
        rows = repo.find(collection, where, order_by=order_by)
        return {"total": len(rows), "page": 1, "page_size": len(rows), key: [to_json(r) for r in rows]}

    try:
        page = max(1, int(page or 1))
    except (TypeError, ValueError):
        page = 1
    total = repo.count(collection, where)
    rows = repo.find(collection, where, order_by=order_by,
                     offset=(page - 1) * size, limit=size)
    return {"total": total, "page": page, "page_size": size, key: [to_json(r) for r in rows]}
