"""adapters.queue —— 任务队列适配器。"""

from .inprocess import InProcessTaskQueue  # noqa: F401
from .models import TaskStatus  # noqa: F401
from .rabbitmq import RabbitMQTaskQueue  # noqa: F401

__all__ = ["InProcessTaskQueue", "RabbitMQTaskQueue", "TaskStatus"]