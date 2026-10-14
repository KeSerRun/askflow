"""modules.deliverable.dto —— 交付物请求体。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class TemplateBody(BaseModel):
    """模板保存请求体（name 走路径参数）。"""

    model_config = ConfigDict(extra="ignore")

    label: str = ""
    description: str = ""
    # 主题色（#rrggbb）与模板自定义 CSS（追加在默认样式后，可覆盖）
    accent: str = ""
    css: str = ""
    # 内容字段说明：[{key, label, type}]（供模型按结构填写 content，管理端仅展示/编辑）
    fields: list = []
    # Jinja2 模板 HTML
    html: str = ""
