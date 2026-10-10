"""adapters.queue.models —— 后台任务状态类型（本适配器专属）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TaskStatus:
    """后台任务状态（对象存储/解析任务通用）。

    Attributes:
        task_id: 任务 ID。
        status: pending / running / finished / failed / unknown。
        progress: 进度（0~1）。
        detail: 附加信息。
    """

    task_id: str
    status: str
    progress: float = 0.0
    detail: dict[str, Any] = field(default_factory=dict)
