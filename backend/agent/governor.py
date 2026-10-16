"""上下文压缩：归档原历史，压缩工具调用结果后写回。

两类入口：
- ``compress_history`` / ``truncate_history``：加载历史时对持久化历史做治理；
- ``compress_messages``：工具循环运行中，就地对扁平的 messages 列表做轻量压缩。

压缩时保证 **不切断 Markdown 图片链接**（``![图](url)``），图片 URL 逐字保留。
"""
from __future__ import annotations

import re

from infra.util.logger import logger

_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")


def _image_safe_cut(text: str, cut: int, start: int = 0) -> int:
    """把切割点后移出 Markdown 图片链接，避免 URL 被截断。

    当 ``cut`` 落在 ``![alt](url)`` span 内部时返回该 span 末尾，否则原样返回。
    """
    for m in _IMAGE_RE.finditer(text, start):
        if m.start() >= cut:
            break
        if m.start() < cut < m.end():
            return m.end()
    return cut


def _compress_tool_content(content: str, compression_ratio: float) -> str:
    """按 4 等分保留每段前 ``compression_ratio`` 比例，且不切断图片链接。"""
    bk_len = max(1, len(content) // 4)
    parts = []
    for i in range(4):
        start = i * bk_len
        end = len(content) if i == 3 else (i + 1) * bk_len
        keep = max(1, int((end - start) * compression_ratio))
        cut = _image_safe_cut(content, start + keep, start)
        parts.append(content[start:cut])
    return "".join(parts)


def _archive(data_store: object, session_id: str, history: list, label: str):
    """归档原历史：数据存储提供 archive_history 方法则调用，无则跳过。"""
    if hasattr(data_store, "archive_history"):
        data_store.archive_history(session_id, history)
        logger.debug(f"历史已归档({label}): session={session_id}")


def compress_history(
    data_store: object,
    session_id: str,
    history: list,
    compression_ratio: float = 0.3,
    archive: bool = True,
) -> bool:
    """压缩会话历史中的工具调用结果。

    将每条 turn 中的 tool 消息 content 按 4 等分 + ratio 截断（不切断图片链接），写回原文件。

    Args:
        data_store: 历史服务实例（HistoryService）。
        session_id: 会话 ID，用于写回和归档。
        history: 历史数据列表（直接传入，不内部加载）。
        compression_ratio: 每块保留比例，默认 0.3。
        archive: 是否在压缩前归档原文件。

    Returns:
        是否执行了压缩。
    """
    if not history:
        return False

    turn_count = sum(1 for e in history if e.get("type") == "turn")
    total_chars = sum(
        len(str(m.get("content", "") or ""))
        for e in history if e.get("type") == "turn"
        for m in e.get("messages", [])
    )

    logger.debug(
        f"压缩历史: session={session_id}, "
        f"{turn_count} 轮, {total_chars} chars, "
        f"ratio={compression_ratio}"
    )

    if archive:
        _archive(data_store, session_id, history, "compress")

    compressed_count = 0
    saved_chars = 0
    for entry in history:
        if entry.get("type") != "turn":
            continue
        for msg in entry.get("messages", []):
            if msg.get("role") == "tool" and isinstance(msg.get("content"), str):
                content = msg["content"]
                if len(content) < 200:
                    continue
                new_content = _compress_tool_content(content, compression_ratio)
                saved_chars += len(content) - len(new_content)
                msg["content"] = new_content
                compressed_count += 1

    if hasattr(data_store, "replace_session_history"):
        data_store.replace_session_history(session_id, history)
    logger.debug(
        f"历史压缩完成: 压缩 {compressed_count} 条工具结果, "
        f"节省 {saved_chars} chars"
    )
    return True


def truncate_history(
    data_store: object,
    session_id: str,
    history: list,
    target_chars: int,
    archive: bool = True,
) -> bool:
    """从历史列表中丢弃最早的轮次，直到总字符不超过 target_chars。

    保留 event 类型条目（文件操作记录），只丢弃 qa / turn 条目。

    Args:
        data_store: 数据存储实例。
        session_id: 会话 ID，用于写回和归档。
        history: 历史数据列表（直接传入）。
        target_chars: 目标字符数上限。
        archive: 是否在截断前归档原文件（已归档过则跳过）。

    Returns:
        是否执行了截断。
    """
    if not history or len(history) < 3:
        return False

    total = sum(
        len(str(m.get("content", "") or ""))
        for e in history if e.get("type") in ("turn",)
        for m in e.get("messages", [])
    )
    if total <= target_chars:
        return False

    logger.warning(
        f"截断历史: session={session_id}, "
        f"{len(history)} 条, {total} chars, "
        f"目标 {target_chars} chars"
    )

    if archive:
        _archive(data_store, session_id, history, "truncate")
    # 从最早开始丢弃 qa/turn，保留 event，至少保留最后一条
    keep = []
    dropped = 0
    for i, entry in enumerate(history):
        is_last = (i == len(history) - 1)
        if entry.get("type") == "event":
            keep.append(entry)
            continue
        if total <= target_chars or is_last:
            keep.append(entry)
            continue
        if entry.get("type") == "turn":
            for m in entry.get("messages", []):
                total -= len(str(m.get("content", "") or ""))
        elif entry.get("type") == "qa":
            total -= len(str(entry.get("user", "") or ""))
            total -= len(str(entry.get("assistant", "") or ""))
        dropped += 1

    if hasattr(data_store, "replace_session_history"):
        data_store.replace_session_history(session_id, keep)
    logger.debug(
        f"历史截断完成: 丢弃 {dropped} 条, "
        f"剩余 {len(keep)} 条"
    )
    return True


def compress_messages(
    messages: list,
    compression_ratio: float = 0.3,
    keep_recent: int = 4,
    min_chars: int = 200,
) -> bool:
    """就地压缩扁平 messages 中较早的工具结果（不动最近 ``keep_recent`` 条）。

    与 :func:`compress_history` 的区别：这里操作的是工具循环运行中的
    OpenAI 格式消息列表，只改写 ``role=tool`` 消息的 content，保持角色 /
    顺序 / ``tool_call_id`` 配对不变，因此压缩后仍是合法的 LLM 输入。
    用于在单次运行中腾出上下文预算，避免直接熔断提前结束。

    Args:
        messages: OpenAI 格式消息列表（就地修改）。
        compression_ratio: 每段保留比例。
        keep_recent: 末尾保留不压缩的消息条数（保护当前回合的上下文）。
        min_chars: 小于该长度的工具结果跳过（压缩无意义）。

    Returns:
        是否发生了压缩。
    """
    if not messages:
        return False
    guard = max(0, len(messages) - keep_recent)
    changed = False
    for msg in messages[:guard]:
        if not isinstance(msg, dict) or msg.get("role") != "tool":
            continue
        content = msg.get("content")
        if not isinstance(content, str) or len(content) < min_chars:
            continue
        new_content = _compress_tool_content(content, compression_ratio)
        if len(new_content) < len(content):
            msg["content"] = new_content
            changed = True
    return changed
