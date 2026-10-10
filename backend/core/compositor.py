"""compositor —— 组合根（Composition Root）。

全项目唯一允许"认识所有模块"的地方：
  1. 从环境变量构建不可变 AppConfig
  2. 按 .env 开关选择具体 adapter 实现（storage/vector/object/queue/cache ...）
  3. 组装各应用服务与服务注册表

业务层、适配器之间互相不认识，组合仅发生在此处。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from agent import IntegratedSystem
from config import AppConfig, load_app_config
from infra.adapters.cache import InMemoryCache, RedisCache
from infra.adapters.llm import OpenAIChatModel, OpenAIEmbedder
from infra.adapters.object import LocalObjectStore, MinioObjectStore
from infra.adapters.queue import InProcessTaskQueue, RabbitMQTaskQueue
from infra.adapters.storage import CachedRepo, MySQLRepo, SqliteRepo
from infra.adapters.vector import CachedVectorStore, FaissVectorStore, MilvusVectorStore
from infra.llm_client import OpenAIClient
from modules.auth import AuthService
from modules.dashboard.service import DashboardService
from modules.document.service import DocumentService
from modules.document.storage_service import StorageService
from modules.history import HistoryService
from modules.query import QueryService
from modules.session import SessionService
from modules.user import UserService


@dataclass
class Container:
    """装配完成的应用容器。

    组件为具体 adapter 实例（按 .env 开关选定）；services 为应用服务注册表。
    """

    config: AppConfig
    chat_model: object
    embedder: object
    vector_store: object
    repo: object
    user_service: object
    history_service: object
    object_store: object
    cache: object = field(default_factory=InMemoryCache)
    task_queue: object = field(default_factory=InProcessTaskQueue)
    services: dict = field(default_factory=dict)

    def get(self, name: str):
        """按名取服务（无则 KeyError）。"""
        return self.services[name]


def _build_llm_client(cfg: AppConfig) -> OpenAIClient:
    """构造 LLM 对话客户端。

    opencode Go 端点（``https://opencode.ai/zen/go/v1``）要求 ``x-opencode-session``
    头用于路由；此处按进程生成一个会话标识随所有聊天请求发送（其它端点会忽略该头）。
    """
    return OpenAIClient(
        api_key=cfg.llm_api_key,
        base_url=cfg.llm_base_url,
        timeout=cfg.llm_timeout,
        max_retries=cfg.llm_max_retries,
        default_headers={"x-opencode-session": uuid.uuid4().hex},
    )


def _build_embed_client(cfg: AppConfig) -> OpenAIClient:
    """构造嵌入客户端（独立端点/密钥）。"""
    return OpenAIClient(
        api_key=cfg.embed_api_key,
        base_url=cfg.embed_base_url,
        timeout=cfg.llm_timeout,
        max_retries=cfg.llm_max_retries,
    )


def build_container(cfg: AppConfig) -> Container:
    """构建应用容器。

    Args:
        cfg: 应用配置（必填，由调用方显式加载/提供）。

    Returns:
        Container: 装配完成的对象图。
    """

    # ── LLM 对话 / 嵌入 ──
    chat_model = OpenAIChatModel(_build_llm_client(cfg), cfg.llm_model)
    embedder = OpenAIEmbedder(
        _build_embed_client(cfg), cfg.embed_model, cfg.embed_dim
    )

    # ── 缓存（进程内 / Redis）——数据层缓存（仓储 / 向量库）共用 ──
    if cfg.cache_backend == "redis":
        cache = RedisCache(cfg.redis_url)
    else:
        cache = InMemoryCache()

    # ── 通用对象仓储（按 storage_backend 选具体后端，读缓存 + 写失效） ──
    BackendRepo = MySQLRepo if cfg.storage_backend == "mysql" else SqliteRepo
    repo = CachedRepo(BackendRepo(cfg.storage_db_url), cache)
    # ── 向量库（读取带缓存，写入失效） ──
    if cfg.vector_backend == "milvus":
        vector_store = CachedVectorStore(MilvusVectorStore(
            embedder=embedder,
            uri=cfg.vector_milvus_uri,
            token=cfg.vector_milvus_token,
            collection_name=cfg.vector_milvus_collection,
            default_top_k=cfg.retrieval_top_k,
        ), cache)
    else:
        vector_store = CachedVectorStore(FaissVectorStore(
            embedder=embedder,
            index_dir=cfg.storage_vector_dir,
            default_top_k=cfg.retrieval_top_k,
        ), cache)

    # ── 对象存储（上传文档 / MinerU 产物） ──
    if cfg.object_backend == "minio":
        object_store = MinioObjectStore(
            endpoint=cfg.object_minio_endpoint,
            access_key=cfg.object_minio_access_key,
            secret_key=cfg.object_minio_secret_key,
            bucket=cfg.object_minio_bucket,
            secure=cfg.object_minio_secure,
        )
    else:
        object_store = LocalObjectStore(cfg.storage_data_dir)

    # ── 任务队列（本地线程池 / RabbitMQ） ──
    if cfg.mq_backend == "rabbitmq":
        task_queue = RabbitMQTaskQueue(
            url=cfg.mq_rabbitmq_url,
            queue=cfg.mq_parse_queue,
            status_store=cache,
            consumers=cfg.mineru_max_concurrency,
        )
    else:
        task_queue = InProcessTaskQueue(max_workers=cfg.mineru_max_concurrency)

    # ── 应用服务 ──
    user_service = UserService(repo)
    history_service = HistoryService(repo)
    storage_service = StorageService(data_dir=cfg.storage_data_dir, max_user_mb=cfg.upload_max_user_mb)
    document_service = DocumentService(
        vector=vector_store,
        history=history_service,
        storage=storage_service,
        data_dir=cfg.storage_data_dir,
        mineru_max_concurrency=cfg.mineru_max_concurrency,
    )
    auth_service = AuthService(
        user_service,
        jwt_secret=cfg.auth_jwt_secret,
        refresh_store=repo,  # refresh token 轮换/吊销落库（复用通用仓储）
    )
    session_service = SessionService(repo, history_service)
    dashboard_service = DashboardService(user_service, vector_store)

    # 组装服务
    services = {
        "document_service": document_service,
        "auth_service": auth_service,
        "storage_service": storage_service,
        "session_service": session_service,
        "user_service": user_service,
        "history_service": history_service,
        "dashboard_service": dashboard_service,
    }

    # 组装容器
    container = Container(
        config=cfg,
        chat_model=chat_model,
        embedder=embedder,
        vector_store=vector_store,
        repo=repo,
        user_service=user_service,
        history_service=history_service,
        object_store=object_store,
        cache=cache,
        task_queue=task_queue,
        services=services,
    )

    # ── Agent 引擎 + 问答用例（需要已装配完成的容器） ──
    system = IntegratedSystem(container)
    container.services["system"] = system
    container.services["query_service"] = QueryService(system)

    return container


# ── 进程级容器单例（确保全局唯一，避免重复装配） ──

_container: Container | None = None


def get_container() -> Container:
    """返回进程级容器单例（首次调用时构建）。

    所有消费方（app 入口 / core.deps 等）共用同一实例，避免重复构建。
    """
    global _container
    if _container is None:
        _container = build_container(load_app_config())
    return _container
