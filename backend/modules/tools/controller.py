"""管理后台 API - 工具管理 Controller。

工具定义（元数据 + handler 代码）存数据库，管理端可增 / 改 / 删 / 启停 / 试跑；
运行时由 ``agent.tools.registry.load_defs`` 按数据库装载。
"""

import json

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, ConfigDict, Field

from agent.tools import registry as tool_registry
from agent.tools.registry import ToolContext
from config import conf
from core.concurrency import to_thread
from core.deps import require_admin, system, tool_service
from . import vo as views

router = APIRouter(prefix="/api/admin/tools", tags=["admin"])


def _reload() -> None:
    """按数据库最新定义重建运行时注册表（增删改即时生效）。"""
    tool_registry.load_defs(tool_service.runtime_defs())


class ToolBody(BaseModel):
    """新增工具的请求体。"""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=64)
    description: str = ""
    parameters: dict = {}
    code: str = Field(min_length=1, description="handler 代码，须定义 handle(args, ctx)")
    handler_module: str | None = None
    enabled: bool = True
    concurrent_safe: bool = False


class ToolPatch(BaseModel):
    """更新工具的请求体（仅存在的字段会被更新）。"""

    model_config = ConfigDict(extra="forbid")

    description: str | None = None
    parameters: dict | None = None
    code: str | None = None
    handler_module: str | None = None
    enabled: bool | None = None
    concurrent_safe: bool | None = None
    sort_order: int | None = None


class ToolTestBody(BaseModel):
    """试跑工具的请求体。"""

    model_config = ConfigDict(extra="forbid")

    args: dict = {}


@router.get("")
def list_tools(
    page: int = Query(1, ge=1),
    page_size: int = Query(0, ge=0, le=500),
    keyword: str | None = Query(None),
    user: dict = Depends(require_admin),
):
    """分页列出工具定义（含代码）；``page_size<=0`` 表示全部；keyword 匹配名称/描述。"""
    return views.ok(tool_service.page_list(page=page, page_size=page_size, keyword=keyword))


@router.post("")
def create_tool(body: ToolBody, user: dict = Depends(require_admin)):
    """新增工具（预编译 handler 代码校验）。"""
    result = tool_service.create(**body.model_dump())
    _reload()
    return views.ok(result)


@router.post("/reset")
def reset_builtin_tools(user: dict = Depends(require_admin)):
    """重置系统工具：把内建工具恢复为 ``@tool`` 声明定义（覆盖管理员改动），自定义工具不受影响。"""
    result = tool_service.reset_builtins()
    _reload()
    return views.ok(result)


@router.post("/reset_call_counts")
def reset_tool_call_counts(user: dict = Depends(require_admin)):
    """重置所有工具调用次数为 0。"""
    return views.ok(tool_service.reset_call_counts())


@router.put("/{name}")
def update_tool(name: str, body: ToolPatch, user: dict = Depends(require_admin)):
    """更新工具的元数据 / 代码 / 启停。"""
    data = body.model_dump(exclude_unset=True)
    result = tool_service.update(name, **data)
    _reload()
    return views.ok(result)


@router.delete("/{name}")
def delete_tool(name: str, user: dict = Depends(require_admin)):
    """删除工具定义。"""
    tool_service.remove(name)
    _reload()
    return views.deleted(name)


@router.post("/{name}/source")
async def upload_tool_source(
    name: str,
    file: UploadFile = File(...),
    user: dict = Depends(require_admin),
):
    """上传自定义工具源代码（仅 .py），保存到 ``data/custom_tools/{name}.py`` 并校验模块可加载。"""
    if not file.filename or not file.filename.lower().endswith(".py"):
        raise HTTPException(status_code=400, detail="仅支持 .py 源码文件")
    content = await file.read()
    result = await to_thread(tool_service.save_custom_source, name, content)
    return views.ok(result)


@router.get("/{name}/source")
def get_tool_source(name: str, user: dict = Depends(require_admin)):
    """读取自定义工具源码文本（custom_tools/{name}.py）。"""
    try:
        return views.ok({"code": tool_service.read_custom_source(name)})
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{name}/test")
async def test_tool(name: str, body: ToolTestBody, user: dict = Depends(require_admin)):
    """试跑工具：用真实运行时上下文执行 handler，返回输出（最多截断 2000 字符）。"""
    tool = tool_registry.get(name)
    if tool is None:
        raise HTTPException(status_code=404, detail=f"工具 {name} 未启用或不存在")

    ctx = ToolContext(
        vector_store=getattr(system, "vector_store", None),
        data_store=getattr(system, "data_store", None),
        session_id="tool-admin-test",
        workflow_router=getattr(
            getattr(getattr(system, "tool_loop", None), "system_context", None),
            "workflow_router", None,
        ),
        config=conf,
        cache=getattr(system, "cache", None),
        object_store=getattr(system, "object_store", None),
    )
    try:
        result = await to_thread(
            tool_registry.dispatch,
            name,
            json.dumps(body.args or {}, ensure_ascii=False),
            ctx=ctx,
        )
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"工具执行失败: {e}")
    return views.ok({"name": name, "result": (result or "")[:2000]})