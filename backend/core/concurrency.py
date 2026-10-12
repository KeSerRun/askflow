"""core.concurrency —— 同步阻塞调用的异步卸载工具。

统一走 Starlette 的 ``run_in_threadpool``（= anyio 线程池），与 FastAPI 的
``def`` 接口 / 同步依赖 / SSE 迭代**共用同一个线程池与限流器**（默认 40）。

两个入口：
  - ``to_thread``      业务路径：异常向上抛（交给全局异常处理器映射 HTTP）；
  - ``to_thread_safe`` 非关键路径（日志/调用记录等）：失败只告警，绝不抛出。
"""

from __future__ import annotations

from typing import Any, Callable, TypeVar

from starlette.concurrency import run_in_threadpool

from infra.util.logger import logger

T = TypeVar("T")


async def to_thread(func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """在线程池执行同步阻塞函数，返回其结果（异常向上抛出）。

    Args:
        func: 同步函数。
        *args / **kwargs: 透传给 func 的位置/关键字参数。
    """
    return await run_in_threadpool(func, *args, **kwargs)


async def to_thread_safe(
    func: Callable[..., T], *args: Any, tag: str = "", **kwargs: Any
) -> T | None:
    """在线程池执行同步阻塞函数；失败只告警不抛（best-effort）。

    Args:
        func: 同步函数。
        *args / **kwargs: 透传给 func 的位置/关键字参数。
        tag: 日志前缀标识（缺省用函数名）。

    Returns:
        函数返回值；失败时为 None。
    """
    try:
        return await run_in_threadpool(func, *args, **kwargs)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[{tag or getattr(func, '__name__', 'task')}] 后台调用失败: {e}")
        return None
