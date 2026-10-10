"""上下文压缩：归档原历史，压缩工具调用结果后写回。"""
from __future__ import annotations

from infra.logger import logger


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

    将每条 turn 中的 tool 消息 content 按 4 等分 + ratio 截断，写回原文件。

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
                bk_len = max(1, len(content) // 4)
                parts = []
                for i in range(4):
                    block = content[i * bk_len : (i + 1) * bk_len]
                    keep = max(1, int(len(block) * compression_ratio))
                    parts.append(block[:keep])
                new_content = "".join(parts)
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