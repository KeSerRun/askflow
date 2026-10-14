"""modules/query/dto.py —— 问答入参。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class QueryBody(BaseModel):
    """问答请求体。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    session_id: str = Field(min_length=1)
    question: str = ""
    stream: bool = False
    style: str | None = None
    workflow: str | None = None
    # 附带图片（剪贴板粘贴→上传得到的对象键），模型可用 search_knowledge_base(images=[...]) 图文检索
    images: list[str] | None = None


class SessionIdBody(BaseModel):
    """仅含 session_id 的请求体（中断问答）。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    session_id: str = Field(min_length=1)


class ResumeBody(BaseModel):
    """续跑请求体（断点续跑 / 澄清后继续）。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    session_id: str = Field(min_length=1)
    # 澄清问题的用户回答（选择框所选 / 自定义文本），续跑前注入为一条 user 消息
    answer: str | None = None
    extra_iterations: int = Field(default=0, ge=0, le=20)
    # True → 返回 SSE 事件流（与 /api/query 一致）；False → 返回 {"answer": str}
    stream: bool = False
