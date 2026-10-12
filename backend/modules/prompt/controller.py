"""管理后台 API - Prompt 管理（identity / workflow / style）。

全部接口要求管理员（``require_admin``）。业务在 ``PromptService``：
- 增删改查 ``identity/{Name}.md``，并通过 ``/identity/{Name}/activate`` 切换当前身份；
- 增删改查 ``workflow/{Name}.md`` 与 ``style/{name}/SKILL.md``；
保存/删除/切换后自动热重载 SystemContext。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from core.app_errors import AppError
from core.deps import prompt_service, require_admin
from .dto import PromptContentBody

router = APIRouter(prefix="/api/admin/prompts", tags=["admin"])


@router.get("")
def list_prompts(user: dict = Depends(require_admin)):
    """Prompt 概览：identity 列表 + 活动身份 + workflow 列表 + style 列表（含元信息）。"""
    return prompt_service.overview()


@router.get("/identity")
def list_identities(user: dict = Depends(require_admin)):
    """身份列表与当前活动身份。"""
    return prompt_service.identity_list()


@router.get("/identity/{name}")
def get_identity(name: str, user: dict = Depends(require_admin)):
    """读取单个身份 prompt 文件内容。"""
    try:
        return prompt_service.get_identity(name)
    except AppError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.put("/identity/{name}")
def update_identity(name: str, body: PromptContentBody, user: dict = Depends(require_admin)):
    """创建 / 更新身份 prompt（按文件名）。"""
    try:
        return prompt_service.save_identity(name, body.content)
    except AppError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/identity/{name}")
def delete_identity(name: str, user: dict = Depends(require_admin)):
    """删除身份 prompt 文件。"""
    try:
        return prompt_service.delete_identity(name)
    except AppError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/identity/{name}/activate")
def activate_identity(name: str, user: dict = Depends(require_admin)):
    """切换当前使用的身份。"""
    try:
        return prompt_service.set_active_identity(name)
    except AppError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/workflow/{name}")
def get_workflow(name: str, user: dict = Depends(require_admin)):
    """读取单个工作流 prompt 文件内容。"""
    try:
        return prompt_service.get_item("workflow", name)
    except AppError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.put("/workflow/{name}")
def save_workflow(name: str, body: PromptContentBody, user: dict = Depends(require_admin)):
    """创建 / 更新工作流 prompt（按文件名）。"""
    try:
        return prompt_service.save_item("workflow", name, body.content)
    except AppError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/workflow/{name}")
def delete_workflow(name: str, user: dict = Depends(require_admin)):
    """删除工作流 prompt 文件。"""
    try:
        return prompt_service.delete_item("workflow", name)
    except AppError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/style/{name}")
def get_style(name: str, user: dict = Depends(require_admin)):
    """读取单个风格 prompt（SKILL.md）内容。"""
    try:
        return prompt_service.get_item("style", name)
    except AppError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.put("/style/{name}")
def save_style(name: str, body: PromptContentBody, user: dict = Depends(require_admin)):
    """创建 / 更新风格 prompt（按目录名）。"""
    try:
        return prompt_service.save_item("style", name, body.content)
    except AppError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/style/{name}")
def delete_style(name: str, user: dict = Depends(require_admin)):
    """删除风格 prompt（目录）。"""
    try:
        return prompt_service.delete_item("style", name)
    except AppError as e:
        raise HTTPException(status_code=404, detail=str(e))