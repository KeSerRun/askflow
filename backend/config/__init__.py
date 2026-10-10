"""config —— 配置层（单模块思路）。

配置相关的全部内容集中在 ``config.app_config``：
AppConfig（不可变数据） + 命名约定映射（FIELD_TO_ENV / ENV_TO_FIELD）
+ 加载（load_app_config） + 全局门面（conf）。

路径常量见 ``config.paths``，基础工具见 ``config._utils``。
"""

from .app_config import (
    ENV_TO_FIELD,
    FIELD_TO_ENV,
    AppConfig,
    conf,  # noqa: F401
    load_app_config,
)

__all__ = [
    "AppConfig",
    "FIELD_TO_ENV",
    "ENV_TO_FIELD",
    "load_app_config",
    "conf",
]
