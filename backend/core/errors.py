"""core.errors —— 跨层共享的语义异常（不含 HTTP 概念）。

业务服务层抛这些**语义**错误；表示层（``core.http_errors``）负责映射为 HTTP 状态码。
与 ``core/models.py`` 并列：一个是共享数据词汇，一个是共享错误词汇。
"""

from __future__ import annotations


class AppError(Exception):
    """应用错误基类。"""

    def __init__(self, message: str = ""):
        super().__init__(message)


# ── 通用语义 ──


class InvalidInput(AppError):
    """输入非法 / 业务前置条件不满足。"""


class Unauthorized(AppError):
    """未认证。"""


class PermissionDenied(AppError):
    """无权限 / 越界。"""


class NotFound(AppError):
    """资源不存在。"""


class Conflict(AppError):
    """资源冲突。"""


class QuotaExceeded(AppError):
    """配额超限。"""


# ── 领域专用（继承语义基类） ──


class AuthError(AppError):
    """认证领域异常基类。"""


class UsernameAlreadyExists(AuthError):
    """注册时用户名已被占用。"""

    def __init__(self, username: str):
        super().__init__("Username already exists")
        self.username = username


class InvalidCredentials(AuthError):
    """登录用户名或密码不匹配。"""

    def __init__(self, username: str = ""):
        super().__init__("Invalid credentials")
        self.username = username


class InvalidRefreshToken(AuthError):
    """刷新令牌无效 / 过期 / 已被轮换。"""

    def __init__(self, message: str = "Invalid refresh token"):
        super().__init__(message)


class SessionAccessDenied(PermissionDenied):
    """会话不属于当前用户。"""

    def __init__(self, session_id: str = ""):
        super().__init__("Forbidden")
        self.session_id = session_id
