"""modules.deliverable.markdown —— 交付物内容字段的 Markdown → HTML。

模型生成的内容天然是 Markdown（标题/列表/加粗/表格），模板里用 ``| md`` 过滤器渲染；
``escape=True`` 保证不引入原始 HTML（与 Jinja ``autoescape`` 的安全语义一致）。
"""

from __future__ import annotations

import mistune
from markupsafe import Markup

# table/strikethrough/task_lists/url 覆盖模型常用语法（对齐前端 GFM 观感）
_md = mistune.create_markdown(
    escape=True,
    plugins=["table", "strikethrough", "task_lists", "url"],
)


def md_to_html(text: object) -> Markup:
    """把 Markdown 文本转成安全的 HTML（返回 Markup，供 Jinja 不转义输出）。"""
    if text is None:
        return Markup("")
    if not isinstance(text, str):
        text = str(text)
    text = text.strip()
    if not text:
        return Markup("")
    return Markup(_md(text).strip())


def md_filter(text: object) -> Markup:
    """Jinja 过滤器：``{{ content.summary | md }}``。"""
    return md_to_html(text)
