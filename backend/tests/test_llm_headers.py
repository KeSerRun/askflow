"""LLM 适配器端点头推断单测：opencode 注入会话头，其它端点不注入。"""

import unittest

from infra.adapters.llm.openai import resolve_default_headers


class DefaultHeadersTest(unittest.TestCase):
    def test_opencode_gets_session_header(self):
        h = resolve_default_headers("https://opencode.ai/zen/go/v1")
        self.assertIn("x-opencode-session", h)
        self.assertRegex(h["x-opencode-session"], r"^[0-9a-f]{32}$")

    def test_session_value_is_random(self):
        a = resolve_default_headers("https://opencode.ai/zen/go/v1")
        b = resolve_default_headers("https://opencode.ai/zen/go/v1")
        self.assertNotEqual(a["x-opencode-session"], b["x-opencode-session"])

    def test_other_endpoints_have_no_header(self):
        for url in (
            "https://api.commandcode.ai/provider/v1",
            "https://api.openai.com/v1",
            None,
            "",
        ):
            self.assertEqual(resolve_default_headers(url), {}, url)


if __name__ == "__main__":
    unittest.main()
