"""工具注册中心：ToolRegistry + ToolContext + ToolDef + DB 装载

设计目标:
  - 工具通过 registry.register() 注册，不再写 if/elif 链；
  - **运行时工具一律从数据库装载**：``load_defs()`` 读 ``agent_tools`` 行，
    经 ``_resolve_def`` 解析为 ``(args, ctx) -> str`` handler；
  - ``BUILTIN_TOOLS``/``collect_tools`` **仅用于启动时把内建工具种子写入数据库**，
    不参与运行时装载（无兜底注册）。

文件结构：
  - 工具 handler 按功能拆为 ``_kb_handlers`` / ``_web_handlers`` / ``_infra_handlers``，
    各模块只含 ``@tool`` 的 ``_exec_*`` 入口；辅助函数在 ``_common``；
  - 运行时粘合（ctx contextvar / BaseTool 适配）在 ``_context``。
"""

from __future__ import annotations

import importlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass

from infra.util.logger import logger

# ── 数据类定义 ──


@dataclass
class ToolContext:
    """传递给 tool handler 的运行时上下文。

    Attributes:
        vector_store: 向量存储实例，用于知识库检索。
        partition: 当前会话的分区标识（用户分区）。
        data_store: 持久化数据存储实例。
        session_id: 当前会话 ID。
    """
    vector_store: object
    partition: str | None = None
    data_store: object | None = None
    session_id: str = ""
    # 运行时注入（避免 handler 读全局 conf）：对象存储 / 配置对象 / 缓存
    object_store: object | None = None
    config: object | None = None
    cache: object | None = None
    # 工作流路由（read_workflow 等需要）
    workflow_router: object | None = None
    # 交付物服务（create_deliverable 等需要，组合根注入）
    deliverable_service: object | None = None
    # 向前端推送事件（流式下的 emit_event；非流式为 None）
    emit_event: Callable[[dict], None] | None = None


@dataclass
class ToolDef:
    """单个工具的定义。

    Attributes:
        name: 工具名称（唯一标识）。
        description: 工具功能描述。
        parameters: JSON Schema 格式的参数定义。
        handler: 工具执行函数，签名 (args: dict, ctx: ToolContext) -> str。
        source: 注册来源。
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

    _MAX_REPEAT_EXTERNAL_LOOKUPS = 2

    def __init__(self):
        """初始化空的注册中心。"""
        self._tools: dict[str, ToolDef] = {}
        self._concurrent_safe: set[str] = set()   # 并发安全名单（随工具定义注册，DB 驱动）
        self.call_counts: dict[str, int] = {}
        self._external_lookup_counts: dict[str, int] = {}
        self._on_call: Callable[[str], None] | None = None   # 调用后回调（持久化计数）

    def register(
        self,
        name: str,
        description: str,
        parameters: dict,
        handler: Callable[[dict, ToolContext], str],
        source: str = "",
        concurrent_safe: bool = False,
    ) -> ToolDef:
        """注册一个工具。

        如果工具名已存在，会覆盖注册并发出警告。

        Args:
            name: 工具名称（唯一标识）。
            description: 工具功能描述。
            parameters: JSON Schema 格式的参数定义字典。
            handler: 工具执行函数，签名 (args: dict, ctx: ToolContext) -> str。
            source: 注册来源（seed / db）。
            concurrent_safe: 是否可与其他工具并行执行。

        Returns:
            新创建的 ToolDef 实例。
        """
        if name in self._tools:
            logger.warning(f"工具 {name!r} 被覆盖注册")
        tool = ToolDef(name=name, description=description,
                       parameters=parameters, handler=handler, source=source)
        self._tools[name] = tool
        if concurrent_safe:
            self._concurrent_safe.add(name)
        else:
            self._concurrent_safe.discard(name)
        return tool

    @property
    def schemas(self) -> list[dict]:
        """获取所有已注册工具的 OpenAI 兼容 schema 列表。"""
        return [t.schema for t in self._tools.values()]

    def get(self, name: str) -> ToolDef | None:
        """根据工具名称查找已注册的工具定义。"""
        return self._tools.get(name)

    def is_concurrent_safe(self, tool_name: str) -> bool:
        """判断工具是否可以与其他工具并行执行（并发安全名单随定义注册）。"""
        return tool_name in self._concurrent_safe

    def partition_tool_batches(self, tool_calls: list[dict]) -> list[list[dict]]:
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
            if self.is_concurrent_safe(name):
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
        """每轮请求开始时调用，重置重复查询计数。"""
        self._external_lookup_counts.clear()

    def set_call_listener(self, fn) -> None:
        """注册「工具被调用后」回调（用于把计数持久化到 DB）。"""
        self._on_call = fn

    @staticmethod
    def _external_lookup_signature(name: str, args: dict) -> str | None:
        """生成外部查询的稳定签名，用于重复检测（web_search / read_url）。"""
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

        # 持久化计数（agent_tools.call_count）
        if self._on_call is not None:
            try:
                self._on_call(name)
            except Exception:  # noqa: BLE001 计数失败不影响主流程
                pass

        logger.debug(f"工具调用: {name} (累计: {self.call_counts[name]})")

        try:
            result = tool.handler(args, ctx)
            return result or ""
        except Exception as e:
            logger.error(f"工具 {name!r} 执行失败: {e}")
            return f"(工具执行失败: {e}。请尝试其他工具或根据已有信息回答。)"

    def load_defs(self, defs) -> None:
        """以 DB 定义为准重建工具表。

        Args:
            defs: 形如 ``[{name, description, parameters, code, module}]`` 的列表；
                  每项由 ``_resolve_def`` 解析为运行时 handler。
        """
        self._tools.clear()
        for d in defs or []:
            name = (d.get("name") or "").strip()
            if not name:
                continue

            try:
                handler, source = _resolve_def(d)
            except Exception as e:  # noqa: BLE001
                logger.error(f"解析工具 {name!r} 失败: {e}")
                continue

            self.register(
                name,
                d.get("description") or "",
                d.get("parameters") or {},
                handler,
                source=source,
                concurrent_safe=bool(d.get("concurrent_safe", False)),
            )
        logger.info(f"工具注册表已按数据库重建: {sorted(self._tools.keys())}")

    @staticmethod
    def _validate_params(args: dict, schema: dict) -> str | None:
        """轻量参数校验（必填 + 类型）。"""
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


# ── handler 装载 ──

_FUNC_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def build_handler(code: str, module: str | None = None):
    """把**内联 Python 源码**编译为可调用的 ``handle(args, ctx)``。

    代码须定义 ``def handle(args, ctx) -> str``；``module`` 指定时在其模块命名空间内
    execute（共享模块级状态）。

    Raises:
        ValueError: 代码未定义可调用的 ``handle``。
    """
    if module:
        ns = importlib.import_module(module).__dict__
    else:
        ns = {"__builtins__": __builtins__, "json": json, "re": re, "logger": logger}
    exec(compile(code or "", "<agent-tool>", "exec"), ns)
    handler = ns.get("handle")
    if not callable(handler):
        raise ValueError("工具 code 必须定义 handle(args, ctx) 函数")
    return handler


# ── 内建工具：仅用于「启动时种子写入数据库」，不参与运行时装载 ──

BUILTIN_TOOLS = []


def register_custom_tools_package(custom_dir: str) -> None:
    """把 ``custom_dir`` 注册为可导入包 ``custom_tools``（向 sys.modules 注入包对象）。

    之后 ``import custom_tools.{name}`` 即可加载该目录下的源码文件模块，
    供自定义工具的 ``handler_module=custom_tools.{name}`` 在运行时使用。
    """
    import sys
    import types
    from pathlib import Path

    pkg = types.ModuleType("custom_tools")
    pkg.__path__ = [str(Path(custom_dir))]
    pkg.__package__ = "custom_tools"
    sys.modules.setdefault("custom_tools", pkg)


def collect_tools(*modules) -> list[dict]:
    """扫描 handler 模块中的 ``BaseTool``，登记到 ``BUILTIN_TOOLS``（供 seed_builtins 写入库）。"""
    from langchain_core.tools import BaseTool

    BUILTIN_TOOLS.clear()
    for mod in modules:
        modname = getattr(mod, "__name__", "")
        for name in list(vars(mod)):
            obj = getattr(mod, name)
            if not isinstance(obj, BaseTool):
                continue
            fn = getattr(obj, "func", None)
            BUILTIN_TOOLS.append({
                "name": obj.name,
                "module": modname,
                "handler": getattr(fn, "__name__", None) or obj.name,
                "description": getattr(obj, "description", "") or "",
                "parameters": obj.args_schema.model_json_schema(),
                "concurrent_safe": bool((getattr(obj, "metadata", None) or {}).get("concurrency_safe", False)),
            })
    return BUILTIN_TOOLS


def _resolve_def(d: dict) -> tuple[callable, str]:
    """把 DB 定义解析为 ``(args, ctx) -> str`` 运行时 handler（路径唯一，失败即抛错）。

    - ``code`` 为**纯函数名**且提供 ``module`` → 模块属性是 langchain ``BaseTool``，
      用 ``make_runtime_handler`` 适配（``BaseTool.invoke``）；
    - 否则 ``code`` 为**内联 Python**（``def handle(args, ctx)``）→ ``build_handler`` 编译。

    Raises:
        Exception: 模块/函数不存在、或内联代码无法编译。
    """
    code = (d.get("code") or "").strip()
    module = d.get("module")
    if code and module and _FUNC_NAME_RE.match(code):
        mod = importlib.import_module(module)
        obj = getattr(mod, code)
        from langchain_core.tools import BaseTool
        if isinstance(obj, BaseTool):
            from ._context import make_runtime_handler
            return make_runtime_handler(obj), f"{module}:{code}"
        # 自定义源码模块：普通 (args, ctx) -> str 函数直接使用
        if not callable(obj):
            raise ValueError(f"模块 {module} 的 {code} 不可调用")
        return obj, f"{module}:{code}"
    # 内联 Python 代码
    return build_handler(code, module), (module or "db")
