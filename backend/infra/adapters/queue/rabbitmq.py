"""adapters.queue.rabbitmq —— RabbitMQ 任务队列（ports.TaskQueue 实现）。

设计：
  - 单一持久队列承载所有任务类型，消息体含 {task, task_id, payload}
  - 消费者线程注册 handler 后按 task 名分发
  - 任务状态写入注入的 Cache 端口（Redis ⇒ 跨实例可见；InMemory ⇒ 单机）
  - 手动 ack + 消息持久化（投递/处理都不丢消息）
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from typing import Callable, Optional

from infra.logger import logger
from .models import TaskStatus

_STATUS_TTL = 3600


def _status_key(task_id: str) -> str:
    return f"task:status:{task_id}"


class RabbitMQTaskQueue:
    """基于 RabbitMQ 的任务队列适配器。"""

    def __init__(
        self,
        url: str,
        queue: str = "rag.parse",
        status_store: Optional[object] = None,
        consumers: int = 4,
    ):
        """初始化。

        Args:
            url: amqp://user:pass@host:port/。
            queue: 任务队列名。
            status_store: 任务状态存储（Cache 端口；缺省用进程内缓存）。
            consumers: 消费者线程数。
        """
        try:
            import pika  # 延迟导入，避免模块导入即依赖
        except ImportError as e:  # pragma: no cover
            raise ImportError("RabbitMQTaskQueue 需要安装 pika: pip install pika") from e

        self._pika = pika
        self._url = url
        self._queue = queue
        self._status = status_store
        self._handlers: dict[str, Callable[[dict], dict]] = {}
        self._consumers = max(1, consumers)
        self._running = threading.Event()
        self._running.set()
        self._threads: list[threading.Thread] = []
        self._lock = threading.Lock()

    # ── TaskQueue ──

    def register_handler(self, task: str, handler: Callable[[dict], dict]) -> None:
        self._handlers[task] = handler

    def enqueue(self, task: str, payload: dict, **options) -> str:
        import pika

        task_id = uuid.uuid4().hex
        body = json.dumps(
            {"task": task, "task_id": task_id, "payload": payload}, ensure_ascii=False
        )
        self._set_status(task_id, "pending")

        with self._lock:
            conn = pika.BlockingConnection(pika.URLParameters(self._url))
            try:
                chan = conn.channel()
                chan.queue_declare(queue=self._queue, durable=True)
                chan.basic_publish(
                    exchange="", routing_key=self._queue, body=body,
                    properties=pika.BasicProperties(delivery_mode=2),
                )
            finally:
                conn.close()
        return task_id

    def status(self, task_id: str) -> Optional[TaskStatus]:
        data = self._status.get(_status_key(task_id)) if self._status else None
        if data is None:
            return None
        return TaskStatus(
            task_id=task_id,
            status=data.get("status", "unknown"),
            progress=data.get("progress", 0.0),
            detail=data.get("detail", {}),
        )

    def start_consumers(self) -> None:
        for _ in range(self._consumers):
            t = threading.Thread(target=self._consume_loop, daemon=True,
                                 name="mq-worker")
            t.start()
            self._threads.append(t)

    def shutdown(self) -> None:
        self._running.clear()
        for t in self._threads:
            t.join(timeout=3)

    # ── 消费循环 ──

    def _consume_loop(self) -> None:
        while self._running.is_set():
            try:
                conn = self._pika.BlockingConnection(self._pika.URLParameters(self._url))
                chan = conn.channel()
                chan.queue_declare(queue=self._queue, durable=True)
                chan.basic_qos(prefetch_count=1)
                chan.basic_consume(queue=self._queue, on_message_callback=self._on_message)
                while self._running.is_set():
                    conn.process_data_events(time_limit=1)
            except Exception as e:
                logger.warning(f"[mq] 消费者异常，1s 后重连: {e}")
                conn = None
                time.sleep(1)
            finally:
                try:
                    if "conn" in dir() and conn:
                        conn.close()
                except Exception:
                    pass

    def _on_message(self, channel, method, _props, body) -> None:
        """消息回调：分发到 handler 并写回状态。"""
        try:
            try:
                msg = json.loads(body)
            except json.JSONDecodeError:
                channel.basic_ack(delivery_tag=method.delivery_tag)
                return
            task = msg.get("task", "")
            task_id = msg.get("task_id", "")
            payload = msg.get("payload", {})
            self._run(task, task_id, payload)
        finally:
            channel.basic_ack(delivery_tag=method.delivery_tag)

    def _run(self, task: str, task_id: str, payload: dict) -> None:
        self._set_status(task_id, "running")
        try:
            handler = self._handlers.get(task)
            if handler is None:
                raise ValueError(f"未注册的任务类型: {task}")
            result = handler(payload) or {}
            self._set_status(task_id, "finished", 1.0, {"result": result})
        except Exception as e:  # noqa: BLE001
            logger.error(f"[mq] 任务失败 {task} {task_id}: {e}")
            self._set_status(task_id, "failed", detail={"error": str(e)})

    def _set_status(self, task_id: str, status: str, progress: float = 0.0, detail: dict | None = None) -> None:
        if self._status is None:
            return
        self._status.set(
            _status_key(task_id),
            {"status": status, "progress": progress, "detail": detail or {}},
            ttl=_STATUS_TTL,
        )