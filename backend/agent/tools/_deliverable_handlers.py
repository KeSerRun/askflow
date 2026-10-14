"""agent.tools._deliverable_handlers —— 交付物工具。

- ``list_deliverable_templates``：查看可用模板及所需内容字段；
- ``create_deliverable``：按模板把内容渲染成 PDF 交付物并推送到对话（用户可下载）。

说明：模板中的**文本字段按 Markdown 渲染**（标题 / 列表 / 加粗 / 表格），
所以 content 里可以直接写 Markdown；表格单元格建议短文本。
"""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from infra.util.logger import logger

from ._context import current_tool_ctx, tool


def _service(ctx):
    svc = getattr(ctx, "deliverable_service", None)
    if svc is None:
        raise RuntimeError("交付物服务不可用")
    return svc


@tool("list_deliverable_templates", concurrent_safe=True)
def _exec_list_deliverable_templates() -> str:
    """查看可生成的交付物模板：每套模板的标识（template）、用途说明与所需内容字段。

    在调用 create_deliverable 生成交付物前先调用本工具，据返回的 fields 组织 content。
    内容中的文本字段支持 Markdown（会自动渲染进 PDF）。
    """
    ctx = current_tool_ctx()
    items = _service(ctx).list_templates()
    if not items:
        return "(当前没有可用的交付物模板)"
    lines = ["可用的交付物模板（用 create_deliverable 生成）："]
    for t in items:
        lines.append(f"- template={t['name']}　{t.get('label') or ''}：{t.get('description') or ''}")
        for f in t.get("fields") or []:
            lines.append(f"    · {f.get('key')}（{f.get('label') or ''}）: {f.get('type') or 'text'}")
    lines.append("提示：content 的文本字段支持 Markdown（# 标题 / - 列表 / **加粗** / 表格），会自动渲染。")
    return "\n".join(lines)


@tool("create_deliverable")
def _exec_create_deliverable(
    template: Annotated[str, Field(description="模板标识（先用 list_deliverable_templates 查看）")],
    title: Annotated[str, Field(description="交付物标题（同时作为文件名）")],
    content: Annotated[
        dict | None,
        Field(description="按模板 fields 填写的结构化内容（键名与模板字段一致；文本字段支持 Markdown）"),
    ] = None,
) -> str:
    """按指定模板把内容渲染成一份 PDF 交付物，并推送到对话页面供用户下载。

    使用前先用 list_deliverable_templates 选取 template 并按其 fields 组织 content；
    content 的文本字段支持 Markdown（# 标题 / - 列表 / **加粗** / 表格），会自动渲染；
    小节标题由模板生成，字段内从正文或子标题写起即可，不要重复写该小节的大标题；
    生成后请简短告知用户已生成，不必在回答里重复整篇内容。
    """
    ctx = current_tool_ctx()
    svc = _service(ctx)
    try:
        user_id = int(str(ctx.partition or "0") or 0)
    except (TypeError, ValueError):
        user_id = 0
    session_id = ctx.session_id or ""
    if not session_id:
        return "(缺少会话信息，无法生成交付物)"

    meta = svc.create(user_id=user_id, session_id=session_id, template=template, title=title, content=content or {})

    # 落一条历史事件（重开会话后仍能看到、且可下载）
    try:
        if ctx.data_store is not None:
            ctx.data_store.insert_session_event(session_id, "deliverable", [meta["id"], meta["title"]])
    except Exception as e:  # noqa: BLE001
        logger.warning(f"交付物历史事件写入失败: {e}")

    # 流式：把交付物事件推给对话页
    emit = getattr(ctx, "emit_event", None)
    if callable(emit):
        try:
            emit(
                {
                    "type": "deliverable",
                    "id": meta["id"],
                    "title": meta["title"],
                    "name": meta["name"],
                    "size": meta["size"],
                    "template": meta["template"],
                }
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(f"交付物事件推送失败: {e}")

    logger.info(f"交付物已生成: id={meta['id']} template={template} size={meta['size']}")
    return (
        f"已生成交付物《{meta['title']}》（PDF，{meta['size']} 字节）并推送到对话页面，"
        f"用户可直接下载。请在回答中简短说明已生成，无需重复全文。"
    )
