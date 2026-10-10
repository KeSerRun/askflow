"""config.paths —— 项目路径初始化（配置包最底层）。

提供：
  - 计算项目根（config/ 的父目录 = backend/；源码与 Docker 运行一致）
  - .env / .env.default 的绝对路径
  - ``setpath()``：把 backend/ 加入 sys.path（跨工作目录运行时保证顶层包可导入）

``setpath()`` 由应用启动入口显式调用，避免导入期副作用。
"""

from __future__ import annotations

import os
import sys

# 项目根 = config/ 的父目录（backend/）
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_dotenv_file = os.path.join(_project_root, ".env")
_env_default_file = os.path.join(_project_root, ".env.default")


def setpath() -> None:
    """将项目根（backend/）加入 sys.path，保证 ``modules/infra/...`` 等顶层包可导入。

    幂等：重复调用不会重复追加。
    """
    if _project_root not in sys.path:
        sys.path.append(_project_root)
