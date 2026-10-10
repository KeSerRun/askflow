"""modules/user/dto.py —— 用户管理入参。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, field_validator


class CreateUserBody(BaseModel):
    """管理员创建用户。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    username: str
    password: str
    role: str = "user"

    @field_validator("username")
    @classmethod
    def _check_username(cls, v: str) -> str:
        if not v:
            raise ValueError("用户名和密码不能为空")
        if len(v) < 3:
            raise ValueError("用户名长度至少 3 位")
        return v

    @field_validator("password")
    @classmethod
    def _check_password(cls, v: str) -> str:
        if not v:
            raise ValueError("用户名和密码不能为空")
        if len(v) < 6:
            raise ValueError("密码长度至少 6 位")
        return v

    @field_validator("role")
    @classmethod
    def _check_role(cls, v: str) -> str:
        if v not in ("user", "admin"):
            raise ValueError("角色必须为 user 或 admin")
        return v


class ChangeRoleBody(BaseModel):
    """变更用户角色。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    role: str

    @field_validator("role")
    @classmethod
    def _check_role(cls, v: str) -> str:
        if v not in ("user", "admin"):
            raise ValueError("角色必须为 user 或 admin")
        return v


class ResetPasswordBody(BaseModel):
    """重置用户密码。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    password: str

    @field_validator("password")
    @classmethod
    def _check_password(cls, v: str) -> str:
        if not v or len(v) < 6:
            raise ValueError("密码长度至少 6 位")
        return v