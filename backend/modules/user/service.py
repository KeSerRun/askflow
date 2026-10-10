"""modules.user.service —— 用户领域 CRUD（ORM 实体即领域模型）。

唯一性、凭据校验、分页等**领域语义**在本服务实现；数据存取经通用仓储（ORM 实例）。
"""

from __future__ import annotations

from datetime import datetime

from core.errors import Conflict, InvalidInput, NotFound
from infra.adapters.storage import row_to_dict
from infra.logger import logger

from .entity import User


class UserService:
    """用户领域操作。"""

    def __init__(self, repo: object):
        """初始化。

        Args:
            repo: 通用仓储（collection="users"，返回 User 实体）。
        """
        self._repo = repo

    def insert_user(self, username: str, password: str, role: str = "user") -> bool:
        """创建用户（用户名规范化为小写）；已存在返回 False。"""
        name = username.lower()
        if self._repo.find("users", {"username": name}):
            return False
        self._repo.insert("users", User(
            username=name,
            password=password,
            role=role,
            created_at=datetime.now().isoformat(),
        ))
        return True

    def ensure_admins(self, usernames: list[str], passwords: list[str]) -> int:
        """按配置确保超级用户存在（已存在则跳过；逐个忽略失败）。

        Args:
            usernames: 超级用户名列表（与 ``passwords`` 按下标对应）。
            passwords: 超级用户密码列表。

        Returns:
            int: 本次新建的超级用户数量。
        """
        created = 0
        for username, password in zip(usernames, passwords):
            if not username or not password:
                continue
            try:
                if self.insert_user(username, password, role="admin"):
                    created += 1
            except Exception as e:  # noqa: BLE001
                logger.warning(f"创建超级用户 {username!r} 失败: {e}")
        return created

    def delete_user(self, username: str) -> bool:
        return self._repo.delete_where("users", {"username": username.lower()}) > 0

    def check_user_credentials(self, username: str, password: str) -> dict | None:
        """校验凭据；成功返回 ``{"username", "role"}``，失败返回 None。"""
        rows = self._repo.find("users", {"username": username.lower(), "password": password})
        if not rows:
            return None
        return {"username": rows[0].username, "role": rows[0].role}

    def get_all_users(self, page: int = 1, page_size: int = 20) -> dict:
        """分页返回用户（``{"items": [...], "total": N}``）。"""
        page = max(1, page)
        total = self._repo.count("users")
        rows = self._repo.find("users", order_by="id", offset=(page - 1) * page_size, limit=page_size)
        return {"items": [row_to_dict(u) for u in rows], "total": total}

    def update_user_role(self, username: str, new_role: str) -> bool:
        return self._repo.update_where(
            "users", {"username": username.lower()}, {"role": new_role}
        ) > 0

    def update_user_password(self, username: str, new_password: str) -> bool:
        return self._repo.update_where(
            "users", {"username": username.lower()}, {"password": new_password}
        ) > 0

    # ── 管理端用例（含业务规则，抛 AppError） ──

    def create(self, username: str, password: str, role: str = "user") -> None:
        """创建用户；重名抛 409。

        Raises:
            AppError 409: 用户名已存在。
        """
        if self._repo.find("users", {"username": username.lower()}):
            raise Conflict("用户名已存在")
        self.insert_user(username, password, role)

    def remove(self, username: str, current_user: str = "") -> None:
        """删除用户（禁止删除自身）。

        Raises:
            AppError 400: 试图删除当前登录账户。
            AppError 404: 用户不存在。
        """
        if username == current_user:
            raise InvalidInput("不能删除当前登录账户")
        if self._repo.delete_where("users", {"username": username.lower()}) == 0:
            raise NotFound(f"用户 '{username}' 不存在")

    def change_role(self, username: str, role: str) -> None:
        """变更用户角色。

        Raises:
            AppError 404: 用户不存在。
        """
        if self._repo.update_where("users", {"username": username.lower()}, {"role": role}) == 0:
            raise NotFound(f"用户 '{username}' 不存在")

    def reset_password(self, username: str, password: str) -> None:
        """重置用户密码。

        Raises:
            AppError 404: 用户不存在。
        """
        if self._repo.update_where("users", {"username": username.lower()}, {"password": password}) == 0:
            raise NotFound(f"用户 '{username}' 不存在")
