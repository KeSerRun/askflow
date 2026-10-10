"""modules.auth —— 认证模块。"""

from .entity import AuthenticatedUser
from .service import AuthService

__all__ = ["AuthenticatedUser", "AuthService"]
