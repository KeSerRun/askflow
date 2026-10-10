"""config._utils —— 环境/路径基础工具。"""

from __future__ import annotations

import os
from typing import get_args

from .paths import _project_root


def normalize_path(path: str) -> str:
    """将相对路径标准化为基于项目根目录的绝对路径（并折叠 .. /）。"""
    path = os.path.isabs(path) and path or os.path.join(_project_root, path)
    return os.path.normpath(path).replace("\\", "/")


def _strip_quotes(value: str) -> str:
    """去除字符串首尾匹配的引号。"""
    if not value:
        return value
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def _load_dotenv(path: str) -> dict[str, str]:
    """解析指定 .env 文件为键值字典。"""
    result: dict[str, str] = {}
    if not os.path.exists(path):
        return result
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            value = _strip_quotes(value)
            if key and value:
                result[key] = value
    return result


def _to_bool(value) -> bool:
    """将字符串/布尔值解析为布尔。"""
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _unwrap_optional(tp):
    """Optional[X] / X | None → X。"""
    args = get_args(tp)
    return next((a for a in args if a is not type(None)), tp) if args else tp


def _to_env_text(value) -> str:
    """配置值 → .env 行值（list→逗号，bool→true/false，None→none）。"""
    if value is None:
        return "none"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    return str(value)
