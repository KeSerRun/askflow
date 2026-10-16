"""governor 上下文治理单测：工具结果压缩 + 图片 URL 保护 + 运行中压缩。"""

import unittest

from agent.governor import (
    _compress_tool_content,
    _image_safe_cut,
    compress_history,
    compress_messages,
)

IMG = "![图](/api/documents/image/abc.png)"


class FakeStore:
    def __init__(self):
        self.archived = []
        self.replaced = None

    def archive_history(self, session_id, history):
        self.archived.append(session_id)

    def replace_session_history(self, session_id, history):
        self.replaced = history


class ImageSafeCutTest(unittest.TestCase):
    def test_cut_inside_image_moves_past_url(self):
        text = "abc" + IMG + "def"
        # 切割点落在图片链接内部 → 后移到链接末尾
        self.assertEqual(_image_safe_cut(text, 3 + 10), 3 + len(IMG))

    def test_cut_outside_image_unchanged(self):
        self.assertEqual(_image_safe_cut("abcdef", 3), 3)


class CompressToolContentTest(unittest.TestCase):
    def test_image_url_survives_truncation(self):
        content = "x" * 20 + IMG + "y" * 400
        out = _compress_tool_content(content, 0.3)
        self.assertIn(IMG, out)
        self.assertLess(len(out), len(content))

    def test_short_content_roundtrip(self):
        self.assertEqual(_compress_tool_content("abc", 0.3), "abc")


class CompressMessagesTest(unittest.TestCase):
    def test_compresses_old_tool_results_only(self):
        long = "a" * 1000
        msgs = [
            {"role": "tool", "tool_call_id": "1", "content": long},
            {"role": "assistant", "content": ""},
            {"role": "tool", "tool_call_id": "2", "content": long},
            {"role": "user", "content": "q"},
        ]
        changed = compress_messages(msgs, compression_ratio=0.3, keep_recent=2)
        self.assertTrue(changed)
        self.assertLess(len(msgs[0]["content"]), 1000)  # 较旧工具结果被压缩
        self.assertEqual(msgs[2]["content"], long)        # 最近 2 条保持原样
        self.assertEqual(msgs[0]["tool_call_id"], "1")    # 配对信息不变

    def test_all_recent_no_change(self):
        msgs = [{"role": "tool", "tool_call_id": "1", "content": "a" * 1000}]
        self.assertFalse(compress_messages(msgs, keep_recent=4))

    def test_short_results_skipped(self):
        msgs = [{"role": "tool", "tool_call_id": "1", "content": "tiny"}]
        self.assertFalse(compress_messages(msgs, keep_recent=0))


class CompressHistoryTest(unittest.TestCase):
    def test_archives_and_preserves_image_url(self):
        content = "x" * 20 + IMG + "y" * 400
        history = [{"type": "turn", "messages": [
            {"role": "tool", "tool_call_id": "1", "content": content},
        ]}]
        store = FakeStore()
        done = compress_history(store, "s1", history, compression_ratio=0.3)
        self.assertTrue(done)
        self.assertIn(IMG, history[0]["messages"][0]["content"])
        self.assertEqual(store.archived, ["s1"])
        self.assertIsNotNone(store.replaced)


if __name__ == "__main__":
    unittest.main()
