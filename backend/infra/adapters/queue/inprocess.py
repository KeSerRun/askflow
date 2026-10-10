"""adapters.queue.inprocess —— 进程内线程池任务队列。

TasksQueue 的本地实现：同一进程内线程池调度 + 内存任务状态。
切换到 RabbitMQ 时新增 adapter 即可（业务零改动）。
"""

from __future__ import annotations

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Optional

from .models import TaskStatus


def _wait_status(queue: "InProcessTaskQueue", task_id: str, timeout: float = 10.0) -> TaskStatus:
    """轮询任务状态直至终态（供启动消费者的场景使用）。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = queue.status(task_id)
        if status and status.status in ("finished", "failed"):
            return status
        time.sleep(0.05)
    return queue.status(task_id) or TaskStatus(task_id=task_id, status="unknown")


class InProcessTaskQueue:
    """线程池实现；handler 在 enqueue 出来的 worker 线程执行。"""

    def __init__(self, max_workers: int = 4):
        self._handlers: dict[str, Callable[[dict], dict]] = {}
        self._tasks: dict[str, TaskStatus] = {}
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="task-worker")

    # ── TaskQueue ──

    def register_handler(self, task: str, handler: Callable[[dict], dict]) -> None:
        self._handlers[task] = handler

    def enqueue(self, task: str, payload: dict, **options) -> str:
        task_id = uuid.uuid4().hex
        with self._lock:
            self._tasks[task_id] = TaskStatus(task_id=task_id, status="pending")
        self._executor.submit(self._run, task, task_id, payload)
        return task_id

    def status(self, task_id: str) -> Optional[TaskStatus]:
        with self._lock:
            return self._tasks.get(task_id)

    def start_consumers(self) -> None:
        # 线程池模式：无显式消费者，任务由池内线程即时执行
        pass

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    # ── 内部 ──

    def _run(self, task: str, task_id: str, payload: dict) -> None:
        self._mutate(task_id, status="running")
        try:
            handler = self._handlers.get(task)
            if handler is None:
                raise ValueError(f"未注册的任务类型: {task}")
            result = handler(payload) or {}
            self._mutate(task_id, status="finished", progress=1.0, detail={"result": result})
        except Exception as e:  # noqa: BLE001
            self._mutate(task_id, status="failed", detail={"error": str(e)})

    def _mutate(self, task_id: str, **fields) -> None:
        with self._lock:
            status = self._tasks.get(task_id)
            if status is None:
                return
            for k, v in fields.items():
                setattr(status, k, v)