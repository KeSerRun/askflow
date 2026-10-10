"""健康检查：LLM Chat / Embedding / MinerU / 向量库。

提供各外部依赖的连通性校验函数，供 API 路由和桌面端启动时使用。
"""

import time

import requests

from config import conf
from infra.llm_client import OpenAIClient


# ── 单项检查 ────────────────────────────────────────────────────────


def check_chat(client: OpenAIClient | None = None) -> dict:
    """验证 LLM Chat API 连通性。
    发一条 1-token 请求，极小成本（~$0.00002）。
    """
    if not conf.llm_api_key:
        return {"status": "unhealthy", "error": "chat_api_key 未配置"}

    c = client or OpenAIClient(
        api_key=conf.llm_api_key,
        base_url=conf.llm_base_url,
        timeout=10,
        max_retries=0,
    )
    t0 = time.monotonic()
    try:
        c.chat(
            messages=[{"role": "user", "content": "ping"}],
            model=conf.llm_model,
            max_tokens=1,
            temperature=0,
        )
        elapsed = (time.monotonic() - t0) * 1000
        return {"status": "healthy", "latency_ms": round(elapsed, 0)}
    except Exception as e:
        return {"status": "unhealthy", "error": OpenAIClient.classify_error(e)}


def check_embedding(client: OpenAIClient | None = None) -> dict:
    """验证 Embedding API 连通性。
    嵌入一个单次以验证服务端正常，成本可忽略。
    """
    if not conf.embed_api_key:
        return {"status": "unhealthy", "error": "embedding_api_key 未配置"}

    c = client or OpenAIClient(
        api_key=conf.embed_api_key,
        base_url=conf.embed_base_url,
        timeout=10,
        max_retries=0,
    )
    t0 = time.monotonic()
    try:
        vec = c.embed(["ck"], model=conf.embed_model)
        elapsed = (time.monotonic() - t0) * 1000
        dim = len(vec[0]) if vec else 0
        return {"status": "healthy", "latency_ms": round(elapsed, 0), "dimension": dim}
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}


def check_mineru() -> dict:
    """验证 MinerU API 配置：key 格式 + 服务端可达。
    注意：不做完整解析测试（上传→轮询→下载），成本太高。
    """
    if not conf.mineru_api_key:
        return {"status": "unhealthy", "error": "mineru_api_key 未配置"}
    if not conf.mineru_api_key.startswith("eyJ"):
        return {"status": "unhealthy", "error": "mineru_api_key 格式异常（应为 JWT）"}

    try:
        r = requests.head(conf.mineru_base_url, timeout=5)
        if r.status_code < 500:
            return {"status": "healthy", "note": "key 格式正确，服务端可达（未执行完整解析流程）"}
        return {"status": "unhealthy", "error": f"MinerU 服务返回 {r.status_code}"}
    except Exception as e:
        return {"status": "unhealthy", "error": f"MinerU 服务不可达: {e}"}


def check_vector_store(vs=None) -> dict:
    """验证向量库状态（本地内存，无网络请求）。"""
    if vs is None:
        return {"status": "not_initialized"}
    chunks = vs.count() if hasattr(vs, "count") else 0
    return {
        "status": "healthy",
        "chunks": chunks,
        "dimension": getattr(vs, "dimension", 0),
    }


# ── 合并检查 ────────────────────────────────────────────────────────


def run_all(chat_client=None, embed_client=None, vector_store=None) -> dict:
    """运行全部健康检查，合并为一个结果。"""
    checks = {
        "chat": check_chat(chat_client),
        "embedding": check_embedding(embed_client),
        "mineru": check_mineru(),
        "vector_store": check_vector_store(vector_store),
    }
    statuses = [r["status"] for r in checks.values()]
    if "unhealthy" in statuses:
        overall = "unhealthy"
    else:
        overall = "healthy"

    return {"status": overall, "checks": checks}