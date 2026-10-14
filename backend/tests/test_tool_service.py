"""ToolService 单测：种子（幂等）/ 查询 / 增删改 / 注册表装载。"""

import unittest

from agent.tools.registry import ToolRegistry
from infra.adapters.storage import SqliteRepo
from modules.tools import ToolService


class ToolServiceTest(unittest.TestCase):
    def setUp(self):
        self.repo = SqliteRepo("sqlite:///:memory:")
        self.svc = ToolService(self.repo)

    def test_seed_is_idempotent(self):
        first = self.svc.seed_builtins()
        second = self.svc.seed_builtins()
        self.assertEqual(first, 17)
        self.assertEqual(second, 0)

    def test_runtime_defs_include_builtins(self):
        self.svc.seed_builtins()
        defs = self.svc.runtime_defs()
        names = [d["name"] for d in defs]
        self.assertIn("search_knowledge_base", names)
        self.assertIn("set_goal", names)
        for d in defs:
            self.assertTrue(d["code"], f"{d['name']} 应有 handler（函数名/代码）")
            self.assertNotIn("def handle", d["code"], f"{d['name']} 种子 code 应为函数名")
            self.assertIsInstance(d["parameters"], dict)

    def test_load_defs_builds_registry(self):
        self.svc.seed_builtins()
        reg = ToolRegistry()
        reg.load_defs(self.svc.runtime_defs())
        self.assertEqual(len(reg._tools), 17)
        out = reg.dispatch(
            "set_goal", '{"goal": "Briefing"}',
            ctx=ToolContextAdapter(),
        )
        self.assertIn("Briefing", out)

    def test_builtin_tools_declared_by_decorator(self):
        """内建工具由 langchain @tool 装饰（类型签名推导 schema），collect_tools 登记，不再手写列表。"""
        from agent.tools.registry import BUILTIN_TOOLS

        names = {d["name"] for d in BUILTIN_TOOLS}
        self.assertGreaterEqual(len(names), 15)
        skb = next(d for d in BUILTIN_TOOLS if d["name"] == "search_knowledge_base")
        self.assertIn("queries", list(skb["parameters"].get("properties", {})))
        self.assertIn("images", list(skb["parameters"].get("properties", {})))
        self.assertEqual(skb["module"], "agent.tools._kb_handlers")
        self.assertEqual(skb["handler"], "_exec_search_kb")
        rwf = next(d for d in BUILTIN_TOOLS if d["name"] == "read_workflow")
        self.assertEqual(rwf["module"], "agent.tools._infra_handlers")
        self.assertEqual(rwf["handler"], "_exec_read_workflow")
        self.assertIn("name", rwf["parameters"].get("required", []))

    def test_concurrent_safe_tag_from_decorator(self):
        """并发安全标签来自 @tool(concurrent_safe=True) → metadata → collect_tools。"""
        from agent.tools.registry import BUILTIN_TOOLS

        flags = {d["name"]: d.get("concurrent_safe", False) for d in BUILTIN_TOOLS}
        for name in ("search_knowledge_base", "list_knowledge_base_files",
                     "list_session_resources", "read_chunk_context"):
            self.assertTrue(flags[name], f"{name} 应由 @tool 标注为并发安全")
        self.assertFalse(flags["web_search"])
        self.assertFalse(flags["read_knowledge_base_document"])
        self.assertFalse(flags["read_session_document"])

    def test_create_update_remove(self):
        self.svc.seed_builtins()
        tool = self.svc.create(
            name="echo_tool",
            description="回显测试",
            parameters={"type": "object", "properties": {"text": {"type": "string"}}},
            code="def handle(args, ctx):\n    return 'echo:' + str(args.get('text', ''))",
        )
        self.assertEqual(tool["name"], "echo_tool")
        self.assertEqual(self.svc.get("echo_tool")["enabled"], True)

        # 更新禁用
        self.svc.update("echo_tool", enabled=False)
        self.assertEqual(self.svc.get("echo_tool")["enabled"], False)
        enabled = [d["name"] for d in self.svc.runtime_defs()]
        self.assertNotIn("echo_tool", enabled)

        self.svc.update("echo_tool", description="回显测试2", sort_order=5)
        self.assertEqual(self.svc.get("echo_tool")["description"], "回显测试2")

        self.svc.remove("echo_tool")
        self.assertIsNone(self.svc.get("echo_tool"))

    def test_invalid_code_rejected(self):
        with self.assertRaises(Exception):
            self.svc.create(name="bad", description="x", parameters={},
                            code="not a function")

    def test_build_handler_shares_module_state(self):
        """set_goal / complete_goal 的运行时 handler 共享会话目标缓存。"""
        from agent.tools.registry import BUILTIN_TOOLS, _resolve_def

        by_name = {d["name"]: d for d in BUILTIN_TOOLS}
        set_goal, _ = _resolve_def({"name": "set_goal", "module": by_name["set_goal"]["module"],
                                    "code": by_name["set_goal"]["handler"]})
        complete_goal, _ = _resolve_def({"name": "complete_goal", "module": by_name["complete_goal"]["module"],
                                         "code": by_name["complete_goal"]["handler"]})
        ctx = ToolContextAdapter(session_id="goal-s")
        set_goal({"goal": "测试目标"}, ctx)
        out = complete_goal({}, ctx)
        self.assertIn("已完成", out)


class ToolContextAdapter:
    """最小 ctx：提供 set_goal / complete_goal 所需字段。"""

    def __init__(self, session_id="s1"):
        self.session_id = session_id
        self.config = None
        self.vector_store = None
        self.partition = None


if __name__ == "__main__":
    unittest.main()
