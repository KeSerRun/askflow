"""infra.util.api_errors —— 外部 API 错误的用户友好分类。

把 SDK / HTTP 异常转成可读中文文案，供各层复用（不依赖任何具体客户端类型）。
"""

from __future__ import annotations


def classify_error(e: Exception) -> str:
    """将 API 错误分类为用户友好的消息。

    Args:
        e: 捕获的异常对象。

    Returns:
        中文错误描述字符串。
    """
    msg = str(e)
    if "402" in msg or "Insufficient Balance" in msg or "insufficient_balance" in msg:
        return "API 余额不足，请检查账户余额或更换 API Key。"
    if "401" in msg or "Unauthorized" in msg or "invalid_api_key" in msg:
        return "API Key 无效，请在配置中检查 API Key。"
    if "429" in msg or "Rate limit" in msg or "rate_limit" in msg:
        return "API 请求频率过高，请稍后重试。"
    if "500" in msg or "502" in msg or "503" in msg or "server_error" in msg:
        return "API 服务暂时不可用，请稍后重试。"
    if "timeout" in msg.lower():
        return "API 请求超时，请检查网络连接。"
    if "model" in msg.lower() and "not found" in msg.lower():
        return "模型不存在或不可用，请检查模型名称配置。"
    return f"LLM 调用失败: {e}"
