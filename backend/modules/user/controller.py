"""管理后台 API - 用户管理（Controller）

业务规则（重名/不能删自己/不存在）由 ``modules.user.service.UserService`` 承担。
"""
from fastapi import APIRouter, Depends, Query

from core.deps import require_admin, user_service
from infra.util.logger import logger

from . import vo as views
from .dto import ChangeRoleBody, CreateUserBody, ResetPasswordBody

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/users")
def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: dict = Depends(require_admin),
):
    """列出所有用户（分页，响应中脱敏 password / id）。"""
    return views.page(user_service.get_all_users(page=page, page_size=page_size))


@router.post("/users")
def create_user(body: CreateUserBody, user: dict = Depends(require_admin)):
    """创建用户（可指定角色）。

    Raises:
        AppError 409: 用户名已存在。
    """
    user_service.create(body.username, body.password, body.role)
    logger.info(f"管理员创建用户: username={body.username}, role={body.role}")
    return views.created(body.username)


@router.delete("/users/{username}")
def delete_user(username: str, user: dict = Depends(require_admin)):
    """删除用户（禁止删除自身）。

    Raises:
        AppError 400: 试图删除当前登录账户。
        AppError 404: 用户不存在。
    """
    user_service.remove(username, user.get("username", ""))
    logger.info(f"管理员删除用户: {username}")
    return views.deleted(username)


@router.put("/users/{username}/role")
def change_user_role(username: str, body: ChangeRoleBody, user: dict = Depends(require_admin)):
    """变更用户角色。

    Raises:
        AppError 404: 用户不存在。
    """
    user_service.change_role(username, body.role)
    logger.info(f"用户角色变更: {username} -> {body.role}")
    return views.role_updated(username, body.role)


@router.put("/users/{username}/password")
def reset_password(username: str, body: ResetPasswordBody, user: dict = Depends(require_admin)):
    """重置用户密码。

    Raises:
        AppError 404: 用户不存在。
    """
    user_service.reset_password(username, body.password)
    logger.info(f"管理员重置用户密码: {username}")
    return views.password_reset(username)
