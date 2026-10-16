"""tokens 估算单测：宽/窄字符加权 + 消息级汇总（不含 system，含工具参数）。"""

import unittest

from agent.tokens import estimate_messages_tokens, estimate_tokens


class EstimateTokensTest(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(estimate_tokens(""), 0)
        self.assertEqual(estimate_tokens(None), 0)

    def test_wide_chars_one_token_each(self):
        self.assertEqual(estimate_tokens("你好世界"), 4)

    def test_narrow_chars_quarter(self):
        self.assertEqual(estimate_tokens("abcdefgh"), 2)   # 8/4
        self.assertEqual(estimate_tokens("abc"), 1)        # ceil(3/4)

    def test_mixed(self):
        # 2 宽字符 + 4 窄字符 → 2 + 1 = 3
        self.assertEqual(estimate_tokens("你好abcd"), 3)


class EstimateMessagesTokensTest(unittest.TestCase):
    def test_excludes_system_and_counts_tool_args(self):
        messages = [
            {"role": "system", "content": "x" * 400},
            {"role": "user", "content": "你好"},                       # 2
            {"role": "assistant", "content": "",
             "tool_calls": [{"function": {"arguments": "abcdefgh"}}]},  # 2
        ]
        self.assertEqual(estimate_messages_tokens(messages), 4)

    def test_empty(self):
        self.assertEqual(estimate_messages_tokens([]), 0)
        self.assertEqual(estimate_messages_tokens(None), 0)


if __name__ == "__main__":
    unittest.main()
