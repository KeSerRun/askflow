"""agent.tools._common —— 工具 handler 公共辅助。

配置全部经 ToolContext 注入（ctx.config / ctx.data_dir），不读全局状态。
"""

from __future__ import annotations


def _cfg(ctx, key: str, default=None):
    """从 ctx.config 读取配置（无全局回退）。

    Args:
        ctx: ToolContext（须携带 config）。
        key: 配置属性名。
        default: 配置对象缺少该属性时的兜底值。

    Returns:
        配置值。
    """
    config = getattr(ctx, "config", None)
    if config is None:
        return default
    return getattr(config, key, default)


def _data_dir(ctx) -> str:
    """解析数据根目录：优先 ctx.data_dir，其次 ctx.config.storage_data_dir。"""
    config = getattr(ctx, "config", None)
    return getattr(ctx, "data_dir", None) or (getattr(config, "storage_data_dir", "") if config else "")