"""modules.prompt.dto —— Prompt 管理请求体。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class PromptContentBody(BaseModel):
    """Prompt 文件内容（整份 md：frontmatter + 正文，或 identity 纯文本）。"""

    content: str = Field(..., min_length=1, description="提示词文件内容")
