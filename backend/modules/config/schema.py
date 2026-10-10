"""modules.config.schema —— 配置表单 schema（由 AppConfig 自动派生）。

- ``key`` = **环境变量名**（如 ``LLM_MODEL``）——与 `.env`、前端提交一致；
- ``group`` = 由变量名组前缀派生的中文分组（前端据此分块）；
- 类型由 AppConfig 字段类型推断。
"""

from __future__ import annotations

from dataclasses import fields
from typing import get_args, get_type_hints

from config.app_config import AppConfig
from config import FIELD_TO_ENV

# 组前缀 → 中文分组名（用于前端分块）
GROUP_LABELS = {
    "LLM": "对话模型",
    "EMBED": "嵌入模型",
    "MINERU": "MinerU 解析",
    "STORAGE": "存储 / 数据库",
    "RETRIEVAL": "检索",
    "VECTOR": "向量库",
    "OBJECT": "对象存储",
    "REDIS": "Redis",
    "CACHE": "缓存",
    "MQ": "消息队列",
    "AGENT": "Agent",
    "CONTEXT": "上下文治理",
    "SEARCH": "联网搜索",
    "LOG": "日志",
    "AUTH": "认证 / 超级用户",
    "UPLOAD": "上传限制",
    "WEB": "前端",
}

_HINTS = get_type_hints(AppConfig)
_TYPE_MAP = {list: "string", str: "string", bool: "bool", int: "int", float: "float"}


def _infer_type(name: str) -> str:
    """按 AppConfig 字段类型推断控件类型。"""
    tp = _HINTS.get(name)
    args = get_args(tp)
    if args:  # Optional[X] / X | None → 取非 None 分支
        tp = next((a for a in args if a is not type(None)), tp)
    return _TYPE_MAP.get(tp, "string")


def _group_of(env_name: str) -> str:
    """由变量名组前缀取中文分组名（未知则用前缀本身）。"""
    prefix = env_name.split("_", 1)[0]
    return GROUP_LABELS.get(prefix, prefix)


def build_schema() -> list[dict]:
    """从 AppConfig 自动生成表单 schema（key=env 名，group=分组）。"""
    items: list[dict] = []
    for f in fields(AppConfig):
        env_name = FIELD_TO_ENV.get(f.name)
        if not env_name:
            continue
        items.append({
            "key": env_name,
            "label": env_name,
            "group": _group_of(env_name),
            "type": _infer_type(f.name),
        })
    order = {g: i for i, g in enumerate(GROUP_LABELS.values())}
    items.sort(key=lambda x: order.get(x["group"], len(order)))
    return items