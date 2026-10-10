"""modules.storage_service —— 用户上传配额策略。

统计用户上传的原始文档总大小（不含切块缓存），判断是否超限；
admin 角色不受限制。依赖组合根注入的 ``data_dir`` / ``max_user_mb``，
不读全局配置。
"""

from __future__ import annotations

import os

from core.errors import QuotaExceeded


class StorageService:
    """用户上传配额检查。"""

    def __init__(self, *, data_dir: str, max_user_mb: int):
        """初始化。

        Args:
            data_dir: 数据根目录（用于定位 ``uploads/{user}``）。
            max_user_mb: 普通用户存储上限（MB）；<=0 表示不限制。
        """
        self._data_dir = data_dir
        self._max_mb = max_user_mb

    def check(self, username: str, role: str, additional_bytes: int = 0) -> tuple[bool, float, float]:
        """检查用户存储是否超限。

        Args:
            username: 用户名（定位上传目录）。
            role: 用户角色（``"user"`` 或 ``"admin"``）。
            additional_bytes: 额外待写入字节数（预检查）。

        Returns:
            tuple: ``(ok, current_mb, max_mb)``；admin 或未设限时 ``ok=True``。
        """
        max_mb = self._max_mb
        if max_mb <= 0 or role == "admin":
            return True, 0, max_mb

        total_bytes = 0
        upload_dir = os.path.join(self._data_dir, "uploads", username.lower())
        if os.path.isdir(upload_dir):
            for entry in os.scandir(upload_dir):
                if entry.is_file():
                    total_bytes += entry.stat().st_size

        total_bytes += additional_bytes
        current_mb = total_bytes / (1024 * 1024)
        if current_mb >= max_mb:
            return False, round(current_mb, 2), max_mb
        return True, round(current_mb, 2), max_mb

    def enforce(self, username: str, role: str, additional_bytes: int = 0) -> None:
        """断言未超配额。

        Raises:
            AppError 413: 存储空间不足。
        """
        ok, current_mb, max_mb = self.check(username, role, additional_bytes)
        if not ok:
            raise QuotaExceeded(
                f"存储空间不足：已用 {current_mb}MB / 上限 {max_mb}MB，请清理旧文档后再上传"
            )

    def usage(self, username: str, role: str) -> dict:
        """返回存储使用情况（读取失败时回退为默认值）。"""
        try:
            ok, current_mb, max_mb = self.check(username, role)
            return {
                "current_mb": current_mb,
                "max_mb": max_mb,
                "limit_enabled": max_mb > 0 and role != "admin",
                "ok": ok,
            }
        except Exception:
            return {"current_mb": 0, "max_mb": 0, "limit_enabled": False, "ok": True}