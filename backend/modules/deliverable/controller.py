"""交付物 API。

- **用户端**：列出当前会话的交付物、下载某份交付物（PDF）；
- **管理端**：交付物模板的增删改查 + 用样例内容渲染 PDF 预览。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from core.app_errors import AppError
from core.deps import deliverable_service, require_admin, require_auth

from . import vo as views
from .dto import TemplateBody

# 用户端（/api/*）
router = APIRouter(prefix="/api", tags=["deliverables"])

# 管理端（/api/admin/deliverables/*）
admin_router = APIRouter(prefix="/api/admin/deliverables", tags=["admin"])


# ── 用户端 ──


@router.get("/deliverables")
def list_deliverables(session_id: str = Query(...), user: dict = Depends(require_auth)):
    """列出当前会话的交付物（按生成时间正序）。"""
    return views.deliverables(deliverable_service.list_by_session(session_id, user["user_id"]))


@router.get("/deliverables/{deliverable_id}")
def download_deliverable(deliverable_id: str, user: dict = Depends(require_auth)):
    """下载某份交付物（PDF）。"""
    try:
        data, name = deliverable_service.read(deliverable_id, user_id=user["user_id"])
    except AppError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return views.pdf(data, name)


# ── 管理端：模板管理 ──


@admin_router.get("/templates")
def list_templates(user: dict = Depends(require_admin)):
    """列出全部交付物模板（元信息，不含 HTML）。"""
    return views.templates(deliverable_service.list_templates())


@admin_router.get("/templates/{name}")
def get_template(name: str, user: dict = Depends(require_admin)):
    """读取单个模板（含 HTML）。"""
    try:
        return views.template(deliverable_service.get_template(name))
    except AppError as e:
        raise HTTPException(status_code=404, detail=str(e))


@admin_router.put("/templates/{name}")
def save_template(name: str, body: TemplateBody, user: dict = Depends(require_admin)):
    """新增 / 更新模板。"""
    try:
        return views.ok(deliverable_service.save_template(name, body.model_dump()))
    except AppError as e:
        raise HTTPException(status_code=400, detail=str(e))


@admin_router.delete("/templates/{name}")
def delete_template(name: str, user: dict = Depends(require_admin)):
    """删除模板。"""
    try:
        return views.ok(deliverable_service.delete_template(name))
    except AppError as e:
        raise HTTPException(status_code=404, detail=str(e))


@admin_router.post("/templates/{name}/preview")
def preview_template(name: str, user: dict = Depends(require_admin)):
    """用样例内容渲染该模板的 PDF 预览。"""
    try:
        data = deliverable_service.preview(name)
    except AppError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return views.pdf(data, f"{name}.pdf")


@admin_router.post("/templates/reset")
def reset_templates(user: dict = Depends(require_admin)):
    """把内置模板恢复为代码内置版本（覆盖对内置模板的人工改动）。"""
    return views.ok({"restored": deliverable_service.reset_templates()})
