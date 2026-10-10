"""工具注册中心：ToolRegistry + ToolContext + ToolDef

设计目标:
  - 工具通过 registry.register() 注册，不再写 if/elif 链

数据流:
  1. handler 模块在导入时被执行，其中的 _exec_* 函数被注册到 ToolRegistry
  2. __init__.py 调用 register_all_builtins(registry) 完成注册
  3. LLM 通过 registry.dispatch(name, args_json) 调用工具
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable, List, Optional

from infra.logger import logger


# ── 数据类定义 ──


@dataclass
class ToolContext:
    """传递给 tool handler 的运行时上下文。

    Attributes:
        vector_store: 向量存储实例，用于知识库检索。
        partition: 当前会话的分区标识（用户分区）。
        data_store: 持久化数据存储实例。
        session_id: 当前会话 ID。
        workflow_router: 工作流路由实例，用于按需获取工作流内容。
        llm_client: LLM 客户端实例。
    """
    vector_store: object
    partition: Optional[str] = None
    data_store: Optional[object] = None
    session_id: str = ""
    workflow_router: Optional[object] = None
    # 运行时注入（避免 handler 读全局 conf）：数据根目录 / 对象存储 / 配置对象
    data_dir: str = ""
    object_store: Optional[object] = None
    config: Optional[object] = None


@dataclass
class ToolDef:
    """单个工具的定义。

    Attributes:
        name: 工具名称（唯一标识）。
        description: 工具功能描述。
        parameters: JSON Schema 格式的参数定义。
        handler: 工具执行函数，签名 (args: dict, ctx: ToolContext) -> str。
        source: 注册来源模块名。
    """
    name: str
    description: str
    parameters: dict
    handler: Callable
    source: str = ""

    @property
    def schema(self) -> dict:
        """生成 OpenAI 兼容的工具 schema。

        Returns:
            形如 {"type": "function", "function": {"name": ..., "description": ..., "parameters": ...}} 的字典。
        """
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


# ── 注册中心 ──


class ToolRegistry:
    """工具注册中心。

    管理所有注册工具的生命周期，包括注册、查询、调度、并发控制、重复查询拦截和参数校验。
    """

    _CONCURRENT_SAFE = {
        "search_knowledge_base", "read_chunk_context",
        "read_document_titles", "list_documents",
    }

    _MAX_REPEAT_EXTERNAL_LOOKUPS = 2

    def __init__(self):
        """初始化空的注册中心。"""
        self._tools: dict[str, ToolDef] = {}
        self.call_counts: dict[str, int] = {}
        self._external_lookup_counts: dict[str, int] = {}

    def register(
        self,
        name: str,
        description: str,
        parameters: dict,
        handler: Callable[[dict, ToolContext], str],
        source: str = "",
    ) -> ToolDef:
        """注册一个工具。

        如果工具名已存在，会覆盖注册并发出警告。

        Args:
            name: 工具名称（唯一标识）。
            description: 工具功能描述。
            parameters: JSON Schema 格式的参数定义字典。
            handler: 工具执行函数，签名 (args: dict, ctx: ToolContext) -> str。
            source: 注册来源模块名（可选）。

        Returns:
            新创建的 ToolDef 实例。
        """
        if name in self._tools:
            logger.warning(f"工具 {name!r} 被覆盖注册")
        tool = ToolDef(name=name, description=description,
                       parameters=parameters, handler=handler, source=source)
        self._tools[name] = tool
        return tool

    @property
    def schemas(self) -> List[dict]:
        """获取所有已注册工具的 OpenAI 兼容 schema 列表。

        Returns:
            schema 字典列表，每个元素符合 OpenAI function calling 格式。
        """
        return [t.schema for t in self._tools.values()]


    def get(self, name: str) -> Optional[ToolDef]:
        """根据工具名称查找已注册的工具定义。

        Args:
            name: 工具名称。

        Returns:
            ToolDef 实例，未找到时返回 None。
        """
        return self._tools.get(name)

    @classmethod
    def is_concurrent_safe(cls, tool_name: str) -> bool:
        """判断工具是否可以与其他工具并行执行。

        Args:
            tool_name: 工具名称。

        Returns:
            如果工具是并发安全的返回 True，否则返回 False。
        """
        return tool_name in cls._CONCURRENT_SAFE

    @classmethod
    def partition_tool_batches(cls, tool_calls: list[dict]) -> list[list[dict]]:
        """将工具调用分批：并发安全的一批，不安全的一个一个来。

        对应 nanobot 的 _partition_tool_batches 模式。

        Args:
            tool_calls: 工具调用字典列表，每个字典至少含 'name' 键。

        Returns:
            分批后的列表，每个子列表是一批可并行执行的工具调用。
        """
        concurrent = []
        sequential = []
        for tc in tool_calls:
            name = tc.get("name", "") if isinstance(tc, dict) else ""
            if cls.is_concurrent_safe(name):
                concurrent.append(tc)
            else:
                sequential.append(tc)

        batches = []
        if concurrent:
            batches.append(concurrent)
        for tc in sequential:
            batches.append([tc])
        return batches

    def reset_external_lookup_counts(self):
        """每轮请求开始时调用，重置重复查询计数。

        避免跨轮次的重复调用检测误判。
        """
        self._external_lookup_counts.clear()

    @staticmethod
    def _external_lookup_signature(name: str, args: dict) -> str | None:
        """生成外部查询的稳定签名，用于重复检测。

        目前支持 web_search 和 read_url 两种外部查询类型。

        Args:
            name: 工具名称。
            args: 工具参数字典。

        Returns:
            签名字符串，如果该工具不是外部查询则返回 None。
        """
        if name == "web_search":
            q = (args.get("query") or "").strip()
            return f"web_search:{q.lower()}" if q else None
        if name == "read_url":
            url = (args.get("url") or "").strip()
            return f"read_url:{url.lower()}" if url else None
        return None

    def dispatch(self, name: str, args_json: str, *, ctx: ToolContext) -> str:
        """调度执行一个工具。

        完整流程：参数反序列化 → 工具查找 → 参数校验 → 重复查询拦截 →
        调用计数 → handler 执行 → 异常兜底。

        Args:
            name: 工具名称。
            args_json: JSON 字符串格式的工具参数。
            ctx: 工具运行时上下文。

        Returns:
            工具执行结果字符串，异常时返回友好错误提示。
        """
        try:
            args = json.loads(args_json) if args_json else {}
        except json.JSONDecodeError as e:
            logger.warning(f"tool {name!r} 参数 JSON 解析失败 ({e})")
            return f"(工具调用失败: 参数 JSON 解析错误 {e})"

        tool = self._tools.get(name)
        if tool is None:
            logger.warning(f"未注册的工具: {name!r}, 已注册: {sorted(self._tools.keys())}")
            return f"(未知工具: {name})"

        error = self._validate_params(args, tool.parameters)
        if error:
            logger.warning(f"工具 {name!r} 参数校验失败: {error}")
            return f"(工具 {name!r} 参数错误: {error})"

        sig = self._external_lookup_signature(name, args)
        if sig:
            count = self._external_lookup_counts.get(sig, 0) + 1
            self._external_lookup_counts[sig] = count
            if count > self._MAX_REPEAT_EXTERNAL_LOOKUPS:
                logger.warning(f"重复外部查询被拦截: {sig}")
                return (
                    f"(工具 {name} 调用被拦截：已使用完全相同参数查询 {count} 次。"
                    f"请在已有结果中寻找答案，或使用不同的查询词重试。)"
                )

        self.call_counts[name] = self.call_counts.get(name, 0) + 1

        logger.debug(f"工具调用: {name} (累计: {self.call_counts[name]})")

        try:
            result = tool.handler(args, ctx)
            return result or ""
        except Exception as e:
            logger.error(f"工具 {name!r} 执行失败: {e}")
            return f"(工具执行失败: {e}。请尝试其他工具或根据已有信息回答。)"

    @staticmethod
    def _validate_params(args: dict, schema: dict) -> str | None:
        """轻量参数校验。

        检查必填参数是否存在、类型是否匹配。

        Args:
            args: 实际传入的参数。
            schema: JSON Schema 参数定义。

        Returns:
            错误消息字符串，校验通过时返回 None。
        """
        props = schema.get("properties", {})
        required = schema.get("required", [])

        for key in required:
            if key not in args or args[key] is None:
                return f"缺少必填参数: {key}"
            val = args[key]
            if isinstance(val, str) and not val.strip():
                return f"参数 {key} 不能为空"

        for key, val in args.items():
            if key in props:
                expected = props[key].get("type", "")
                if expected == "array" and not isinstance(val, (list, tuple)):
                    return f"参数 {key} 应为数组"
                elif expected == "integer" and not isinstance(val, int):
                    return f"参数 {key} 应为整数"
                elif expected == "boolean" and not isinstance(val, bool):
                    return f"参数 {key} 应为布尔值"

        return None


# ── 内建工具注册 ──


def register_all_builtins(reg: ToolRegistry) -> None:
    """注册全部内建工具。

    Args:
        reg: ToolRegistry 实例
    """

    # -- 基础工具：澄清 / 目标 / 状态 --
    from ._kb_handlers import (
        _exec_search_kb, _exec_read_full_document,
        _exec_list_documents, _exec_read_chunk_context,
        _exec_read_document_titles, _exec_read_section,
        _exec_search_document_content,
    )
    from ._web_handlers import _exec_web_search, _exec_read_url
    from ._infra_handlers import (
        _exec_ask_clarification,
        _exec_set_goal,
        _exec_complete_goal,
        _exec_my,
        _exec_read_workflow,
    )

    reg.register(
        name="ask_user_for_clarification",
        description=(
            "当用户请求模糊（指代不清、未指定具体文档）且已有检索结果不足以推断时，"
            "调用此工具向用户提问以获取补充信息。调用后对话中断，等待用户回复。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "你需要向用户询问的具体问题，比如'请问您指的是本季度的哪一份财报？'",
                },
            },
            "required": ["question"],
        },
        handler=_exec_ask_clarification,
        source=__name__,
    )

    reg.register(
        name="set_goal",
        description=(
            "设置当前会话的持续目标。目标会持续注入 system prompt，"
            "在后续多轮对话中自动保留上下文。适合用户交代需要多步完成的任务时调用。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "goal": {
                    "type": "string",
                    "description": "目标的详细描述，LLM 应该努力完成的目标。",
                },
            },
            "required": ["goal"],
        },
        handler=_exec_set_goal,
        source=__name__,
    )

    reg.register(
        name="complete_goal",
        description=("标记当前目标已完成。当用户确认目标已完成时调用。"),
        parameters={"type": "object", "properties": {}, "required": []},
        handler=_exec_complete_goal,
        source=__name__,
    )

    reg.register(
        name="my",
        description=(
            "查看当前会话的运行时状态和配置（模型、迭代上限、上下文窗口、检索参数等）。"
            "my(action='check') 查看完整状态，my(action='check', key='model') 查看单项。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "要执行的操作：check（查看状态）。",
                },
                "key": {
                    "type": "string",
                    "description": "要查看的配置项关键词。不传则显示全部。",
                },
            },
            "required": ["action"],
        },
        handler=_exec_my,
        source=__name__,
    )

    reg.register(
        name="read_workflow",
        description=(
            "读取工作流的完整分步指令。可用工作流及摘要已在 system prompt 中列出。"
            "如需使用某个工作流，先调用此工具获取完整指令，再按步骤执行。"
            "当前工作流：Briefing（简报）、Comparison（对比）、DeepResearch（深度研究）、"
            "Autoplan（自动规划）、USstocks（美股分析）。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "工作流名称，如 USstocks、Autoplan、DeepResearch",
                },
            },
            "required": ["name"],
        },
        handler=_exec_read_workflow,
        source=__name__,
    )

    reg.register(
        name="search_knowledge_base",
        description=(
            "知识库语义检索（嵌入模型取决于系统配置），覆盖文本、表格、图片图表。"
            "支持多 query 检索（最多 10 个），自动 RRF 融合排序。多 query 可覆盖不同方面或不同数据来源。"
            "set search_system=false 仅搜用户文档。"
            "top_k 指定返回数量，默认取系统候选值，上限由系统检索配置决定。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "queries": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                    "maxItems": 10,
                    "description": (
                        "检索查询列表。简单问题 1 个；多焦点问题拆 2-10 个子查询。"
                        "用名词短语而非完整问句。"
                    ),
                },
                "search_system": {
                    "type": "boolean",
                    "description": ("是否同时搜索系统公开文档。默认为 true（搜索全部）。"
                                     "设为 false 则只搜索用户自己的文档。"),
                    "default": True,
                },
                "top_k": {
                    "type": "integer",
                    "description": (
                        "返回的结果数量（默认取系统候选值，上限由系统配置决定）。"
                        "需要粗略概览时适当减小，需要全面排查时增加。"
                    ),
                },
            },
            "required": ["queries"],
        },
        handler=_exec_search_kb,
        source=__name__,
    )

    reg.register(
        name="read_full_document",
        description=(
            "读取某篇文档的完整全文（Markdown 格式）。支持 offset 分页（默认每页取系统分页值字符）。"
            "文件名必须是文档清单中的完整文件名（含扩展名）。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": (
                        "要读取的文档文件名（含扩展名）。"
                        "必须是文档清单中出现的完整文件名，如 KD指标.pdf"
                    ),
                },
                "offset": {
                    "type": "integer",
                    "description": "字符偏移位置，用于分页读取（默认 0）。末尾会提示后续 offset。",
                    "default": 0,
                },
                "max_chars": {
                    "type": "integer",
                    "description": "本次最多读取字符数（默认取系统分页值，建议不超过其 5 倍）。",
                },
            },
            "required": ["filename"],
        },
        handler=_exec_read_full_document,
        source=__name__,
    )

    reg.register(
        name="read_url",
        description=(
            "读取指定网页的完整文字内容（超时由系统配置决定）。仅限公开可访问的网页。"
            "支持 offset 分页（默认每页取系统分页值字符）。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "要读取的网页完整 URL（必须以 http:// 或 https:// 开头）",
                },
                "offset": {
                    "type": "integer",
                    "description": "读取起始偏移（字符数，默认 0）",
                },
                "max_chars": {
                    "type": "integer",
                    "description": "本次最多读取字符数（默认取系统分页值，建议不超过其 5 倍）。",
                },
            },
            "required": ["url"],
        },
        handler=_exec_read_url,
        source=__name__,
    )

    reg.register(
        name="web_search",
        description=(
            "搜索互联网获取最新信息（实时新闻、数据等知识库未覆盖的内容）。"
            "搜索后端由系统配置决定。返回结果包含标题、摘要和来源链接。"
            "max_results 控制返回数量（1-10，默认 5）。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词，用名词短语或简洁问句。",
                },
                "max_results": {
                    "type": "integer",
                    "default": 5,
                    "description": "返回结果数量（1-10）。",
                },
            },
            "required": ["query"],
        },
        handler=_exec_web_search,
        source=__name__,
    )

    reg.register(
        name="list_documents",
        description=(
            "列出知识库中的文档清单。支持 pattern 关键词过滤（如「KD」「择时」），"
            "list_system=false 仅列用户自己的文档。返回文档名、类型、大小、修改时间。"
            "可先调用此工具查看可用文档，再使用 read_full_document 读取具体内容。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "可选的文件名关键词（如「KD」「财报」），不传则列出全部。",
                },
                "list_system": {
                    "type": "boolean",
                    "description": ("是否同时列出系统公开文档。默认为 true（列出全部）。"
                                     "设为 false 则只列用户自己的文档。"),
                    "default": True,
                },
                "sort_by": {
                    "type": "string",
                    "enum": ["name", "time"],
                    "description": "排序方式：name（按名称，默认）或 time（按修改时间）。",
                    "default": "name",
                },
            },
            "required": [],
        },
        handler=_exec_list_documents,
        source=__name__,
    )

    reg.register(
        name="read_chunk_context",
        description=(
            "读取某一片段前后的相邻文档内容。当检索到的片段内容不完整、"
            "图表标题需要查看正文、同主题片段分散时使用。"
            "chunk_id 从检索结果标头 [id=] 获取，before/after 控制前后取多少块（默认 3，最大 10）。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "chunk_id": {
                    "type": "string",
                    "description": "目标片段的 ID，从检索结果标头 [id=] 字段获取。",
                },
                "before": {
                    "type": "integer",
                    "default": 3,
                    "description": "向前取多少块（默认 3，最大 10）。",
                },
                "after": {
                    "type": "integer",
                    "default": 3,
                    "description": "向后取多少块（默认 3，最大 10）。",
                },
            },
            "required": ["chunk_id"],
        },
        handler=_exec_read_chunk_context,
        source=__name__,
    )

    reg.register(
        name="read_document_titles",
        description=(
            "读取某篇文档的标题目录结构。返回文档内所有级别的标题列表，"
            "方便快速定位感兴趣的内容。再配合 read_section 或 read_full_document 读取具体内容。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "description": "文档文件名（含扩展名），如 KD指标.pdf",
                },
            },
            "required": ["source"],
        },
        handler=_exec_read_document_titles,
        source=__name__,
    )

    reg.register(
        name="read_section",
        description=(
            "根据文档名和标题关键词，读取该标题下的正文内容。"
            "heading 支持模糊匹配。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "description": "文档文件名（含扩展名），如 KD指标.pdf",
                },
                "heading": {
                    "type": "string",
                    "description": "标题关键词，匹配任意级别的标题。如「第一章」「1.1 背景」「风险收益」",
                },
            },
            "required": ["source", "heading"],
        },
        handler=_exec_read_section,
        source=__name__,
    )

    reg.register(
        name="search_document_content",
        description=(
            "在所有知识库文档的全文内容中搜索关键词（大小写不敏感），"
            "返回匹配的文档名和行号。类似于全文 grep。"
            "可指定 source 限定仅搜索某篇文档，max_results 控制返回数量（1-50，默认 10）。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "keyword": {
                    "type": "string",
                    "description": "搜索关键词（大小写不敏感）。",
                },
                "source": {
                    "type": "string",
                    "description": "可选：限定仅搜索某篇文档（含扩展名）。",
                },
                "max_results": {
                    "type": "integer",
                    "default": 10,
                    "description": "最大返回匹配数量（1-50，默认 10）。",
                },
            },
            "required": ["keyword"],
        },
        handler=_exec_search_document_content,
        source=__name__,
    )