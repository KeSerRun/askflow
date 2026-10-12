"""modules.health.service —— 外部服务健康检查（Chat / Embedding / MinerU / SearXNG / Milvus / MinIO）。

只调用各服务配置的 health 接口做探活并计时，**不发起真实业务调用**；
整体 ``status``：任一项 ``unhealthy`` 即 ``unhealthy``。

health 地址解析：显式配置优先；留空则按 base_url 推导
  - LLM：``LLM_BASE_URL`` + ``/models``（OpenAI 兼容网关的通用探活，如 opencode Go）；
  - Embedding：去掉末尾 ``/v1`` 后 + ``/health``（本地 clip-api）；
  - MinerU：base_url + ``/v1/health``；
  - SearXNG：``SEARCH_SEARXNG_URL`` + ``/healthz``（官方健康端点）；
  - Milvus：``MILVUS_HEALTH_URL`` 缺省 ``http://127.0.0.1:9091/healthz``（standalone 健康端口 9091）；
  - MinIO：``MINIO_HEALTH_URL`` 缺省 ``{scheme}://{object_minio_endpoint}/minio/health/live``。
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

import requests

from config import conf

_TIMEOUT = 10


class HealthService:
    """外部服务健康检查（只探 health 接口）。"""

    def run(self) -> dict:
        """并行探测各服务 health 并合并整体状态（总耗时 ≈ 最慢一项）。"""
        urls = {
            "chat": self._url_llm(),
            "embedding": self._url_embed(),
            "mineru": self._url_mineru(),
            "search": self._url_search(),
            "milvus": self._url_milvus(),
            "minio": self._url_minio(),
        }
        with ThreadPoolExecutor(max_workers=len(urls)) as pool:
            futures = {name: pool.submit(self._probe, url) for name, url in urls.items()}
            checks = {name: fut.result() for name, fut in futures.items()}
        statuses = [c["status"] for c in checks.values()]
        overall = "unhealthy" if "unhealthy" in statuses else "healthy"
        return {"status": overall, "checks": checks}

    # ── 单项探测 ──

    @staticmethod
    def _probe(url: str) -> dict:
        """GET 指定 health 地址，返回状态与耗时。

        用 ``perf_counter``（高精度）；``monotonic`` 在 Windows 只有 ~15.6ms 分辨率，
        会让本地服务的耗时变成 0ms 或 15/16ms 的台阶值。
        """
        if not url:
            return {"status": "unhealthy", "error": "未配置 health 地址"}
        t0 = time.perf_counter()
        try:
            r = requests.get(url, timeout=_TIMEOUT)
            elapsed = round((time.perf_counter() - t0) * 1000, 1)
            if r.status_code == 200:
                return {"status": "healthy", "latency_ms": elapsed, "note": url}
            return {"status": "unhealthy", "latency_ms": elapsed,
                    "error": f"health 返回 {r.status_code}: {url}"}
        except Exception as e:  # noqa: BLE001
            elapsed = round((time.perf_counter() - t0) * 1000, 1)
            return {"status": "unhealthy", "latency_ms": elapsed, "error": f"不可达: {url} ({e})"}

    # ── 地址解析 ──

    @staticmethod
    def _root(base: str | None) -> str:
        """去掉末尾 ``/v1``。"""
        b = (base or "").rstrip("/")
        return b[:-3].rstrip("/") if b.endswith("/v1") else b

    def _url_llm(self) -> str:
        if conf.llm_health_url:
            return conf.llm_health_url.rstrip("/")
        base = (conf.llm_base_url or "").rstrip("/")
        return f"{base}/models" if base else ""

    def _url_embed(self) -> str:
        if conf.embed_health_url:
            return conf.embed_health_url.rstrip("/")
        root = self._root(conf.embed_base_url)
        return f"{root}/health" if root else ""

    def _url_mineru(self) -> str:
        if conf.mineru_health_url:
            return conf.mineru_health_url.rstrip("/")
        base = (conf.mineru_base_url or "").rstrip("/")
        return f"{base}/v1/health" if base else ""

    def _url_search(self) -> str:
        base = (conf.search_searxng_url or "").rstrip("/")
        return f"{base}/healthz" if base else ""

    def _url_milvus(self) -> str:
        if conf.milvus_health_url:
            return conf.milvus_health_url.rstrip("/")
        return "http://127.0.0.1:9091/healthz"

    def _url_minio(self) -> str:
        if conf.minio_health_url:
            return conf.minio_health_url.rstrip("/")
        endpoint = (conf.object_minio_endpoint or "").rstrip("/")
        if not endpoint:
            return ""
        if "://" in endpoint:
            root = endpoint
        else:
            scheme = "https" if conf.object_minio_secure else "http"
            root = f"{scheme}://{endpoint}"
        return f"{root}/minio/health/live"
