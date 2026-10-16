"""agent.tokens —— 上下文预算的 token 估算。

不引入 tokenizer 依赖：按字符类别加权估算，跨模型 / 离线可用且结果确定。
- 宽字符（CJK / 假名 / 谚文 / 全角标点）≈ 1 token/字；
- 其余（拉丁字母 / 数字 / 符号 / 空白）≈ 1/4 token/字符（约 4 字符 1 token）。

估算偏保守（略高估），用于预算上限判断更安全。
"""
from __future__ import annotations

import re

# 宽字符：CJK 部首/符号/标点 + 假名 + 谚文 + 统一表意 + 兼容表意 + 全角
_WIDE_RE = re.compile(
    r"[\u1100-\u11ff\u2e80-\u9fff\uac00-\ud7af\uf900-\ufaff\uff00-\uffef]"
)


def estimate_tokens(text: object) -> int:
    """估算单段文本的 token 数（宽字符 1:1，其余约 4 字符 1 token）。"""
    s = text if isinstance(text, str) else str(text or "")
    if not s:
        return 0
    wide = len(_WIDE_RE.findall(s))
    narrow = len(s) - wide
    return wide + (narrow + 3) // 4


def estimate_messages_tokens(messages: list) -> int:
    """估算消息列表的 token 总数（不含 system 消息；含工具调用参数）。"""
    total = 0
    for m in messages or []:
        if not isinstance(m, dict) or m.get("role") == "system":
            continue
        total += estimate_tokens(m.get("content"))
        for tc in m.get("tool_calls") or []:
            fn = tc.get("function") or {}
            total += estimate_tokens(fn.get("arguments"))
    return total
