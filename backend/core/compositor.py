"""compositor —— 组合根（Composition Root）。

全项目唯一允许"认识所有模块"的地方：
  1. 从环境变量构建不可变 AppConfig
  2. 按 .env 开关选择具体 adapter 实现（storage/vector/object/cache ...）
  3. 组装各应用服务与服务注册表

业务层、适配器之间互相不认识，组合仅发生在此处。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from agent import IntegratedSystem
from agent.tools import registry as tool_registry
from config import AppConfig, load_app_config
from config.paths import custom_tools_dir, deliverable_templates_dir, prompts_dir
from infra.adapters.cache import InMemoryCache, RedisCache
from infra.adapters.llm import OpenAIChatModel, OpenAIEmbedder
from infra.adapters.object import MinioObjectStore
from infra.adapters.storage import CachedRepo, MySQLRepo, SqliteRepo
from infra.adapters.vector import CachedVectorStore, MilvusVectorStore
from modules.auth import AuthService
from modules.dashboard.service import DashboardService
from modules.database import entity as _db_entity  # noqa: F401 注册 ORM 模型（chunk_parents 等）
from modules.database.service import DatabaseService
from modules.deliverable import DeliverableService
from modules.document.service import DocumentService
from modules.health.service import HealthService
from modules.history import HistoryService
from modules.logger.db_handler import attach_application_db_logger
from modules.logger.service import LogService, RequestLogService
from modules.logger.stats import RequestStats
from modules.query import QueryService
from modules.session import SessionService
from modules.tools import ToolService
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
    services: dict = field(default_factory=dict)

    def get(self, name: str):
        """按名取服务（无则 KeyError）。"""
        return self.services[name]


def build_container(cfg: AppConfig) -> Container:
    """构建应用容器。

    Args:
        cfg: 应用配置（必填，由调用方显式加载/提供）。

    Returns:
        Container: 装配完成的对象图。
    """

    # ── LLM 对话 / 嵌入 ──
    # 对话/嵌入各自独立的 OpenAI 兼容端点与密钥，直接构造适配器。
    # opencode Go 端点要求 x-opencode-session 头用于路由（其它端点忽略）。
    chat_model = OpenAIChatModel(
        api_key=cfg.llm_api_key,
        base_url=cfg.llm_base_url,
        model=cfg.llm_model,
        timeout=cfg.llm_timeout,
        max_retries=cfg.llm_max_retries,
        default_headers={"x-opencode-session": uuid.uuid4().hex},
    )
    embedder = OpenAIEmbedder(
        api_key=cfg.embed_api_key,
        base_url=cfg.embed_base_url,
        model=cfg.embed_model,
        dimension=cfg.embed_dim,
        timeout=cfg.llm_timeout,
        max_retries=cfg.llm_max_retries,
    )

    # ── 缓存（进程内 / Redis）——数据层缓存（仓储 / 向量库）共用 ──
    if cfg.cache_backend == "redis":
        cache = RedisCache(cfg.redis_url)
    else:
        cache = InMemoryCache()

    # ── 通用对象仓储（按 storage_backend 选具体后端，读缓存 + 写失效） ──
    backend_repo = MySQLRepo if cfg.storage_backend == "mysql" else SqliteRepo
    repo = CachedRepo(backend_repo(cfg.storage_db_url), cache)

    # ── 工具定义（数据库为准）：先种子入内建工具，再装载到注册表 ──
    tool_service = ToolService(repo, custom_tools_dir=custom_tools_dir)
    # 自定义工具源码目录（template/custom_tools）注册为可导入包（custom_tools.*）
    from agent.tools.registry import register_custom_tools_package

    register_custom_tools_package(custom_tools_dir)
    tool_service.seed_builtins()
    # 移除已下线内建工具（read_document_titles / read_section）存量行
    from core.migrate import purge_deprecated_tools
    purge_deprecated_tools(repo)
    tool_registry.load_defs(tool_service.runtime_defs())
    # 工具调用计数持久化到 agent_tools.call_count
    tool_registry.set_call_listener(tool_service.increment_call_count)
    # 用户身份迁移：sessions/request_logs/refresh_tokens 补 user_id 并回填
    from core.migrate import ensure_user_identity
    ensure_user_identity(repo)

    # ── 向量库（仅支持 Milvus；连接失败降级 None，不提供其他后端） ──
    try:
        from modules.database.parent_store import ChunkParentStore
        chunk_parent_store = ChunkParentStore(repo)
    except Exception as e:  # noqa: BLE001
        from infra.util.logger import logger
        logger.warning(f"父块内容存储初始化失败，父块功能禁用: {e}")
        chunk_parent_store = None

    # ── 向量库（仅支持 Milvus；懒连接：构造不建连，首次检索/入库时才连） ──
    vector_store = CachedVectorStore(MilvusVectorStore(
        embedder=embedder,
        uri=cfg.vector_milvus_uri,
        token=cfg.vector_milvus_token,
        collection_name=cfg.vector_milvus_collection,
        default_top_k=cfg.retrieval_top_k,
        parent_store=(chunk_parent_store.save_parent if chunk_parent_store else None),
    ), cache)

    # ── 对象存储（仅支持 MinIO；连接失败降级 None） ──
    try:
        object_store = MinioObjectStore(
            endpoint=cfg.object_minio_endpoint,
            access_key=cfg.object_minio_access_key,
            secret_key=cfg.object_minio_secret_key,
            bucket=cfg.object_minio_bucket,
            secure=cfg.object_minio_secure,
        )
    except Exception as e:  # noqa: BLE001
        from infra.util.logger import logger
        logger.warning(
            f"对象存储不可用（MinIO {cfg.object_minio_endpoint} 初始化失败）→ 已降级："
            f"附件上传 / 交付物生成不可用。原因: {e}"
        )
        object_store = None

    # ── 依赖装配一览（一行；连通性按需查 GET /api/health/check） ──
    from infra.util.logger import logger

    logger.info(
        "依赖装配："
        f"数据库={cfg.storage_backend}(已连接并建表) | 缓存={cfg.cache_backend} | "
        f"向量库=Milvus {cfg.vector_milvus_uri} | 对象存储=MinIO {cfg.object_minio_endpoint} | "
        f"嵌入={cfg.embed_base_url} | 对话={cfg.llm_base_url} | "
        "除数据库/缓存外均为懒连接（首次使用时连接）；连通性见 GET /api/health/check"
    )

    # ── 交付物（模板 + HTML→PDF 渲染 + 生成） ──
    deliverable_service = DeliverableService(
        repo, object_store, deliverable_templates_dir,
    )

    # ── 应用服务 ──
    user_service = UserService(repo)
    history_service = HistoryService(repo)
    document_service = DocumentService(
        vector=vector_store,
        object_store=object_store,
        mineru_max_concurrency=cfg.mineru_max_concurrency,
        max_session_mb=cfg.upload_max_session_mb,
    )
    auth_service = AuthService(
        user_service,
        jwt_secret=cfg.auth_jwt_secret,
        refresh_store=repo,  # refresh token 轮换/吊销落库（复用通用仓储）
    )
    def _cleanup_session(user_id, session_id) -> None:
        """删除会话时的级联清理：会话文件 + 交付物（对象存储与记录）。"""
        document_service.clear_session_files(user_id, session_id)
        deliverable_service.delete_by_session(user_id, session_id)

    session_service = SessionService(repo, history_service, cleanup=_cleanup_session)
    dashboard_service = DashboardService(user_service, vector_store, repo)
    request_log_service = RequestLogService(repo)
    request_stats = RequestStats(cache)   # 请求统计：缓存累加，独立于 request_logs 与环境
    database_service = DatabaseService(
        vector_store, document_service,
        object_store=object_store,
        parent_store=(chunk_parent_store if vector_store else None),
        repo=repo,
        workers=cfg.mineru_max_concurrency,
    )
    # 日志管理（查 app_logs / request_logs 表）+ 应用日志入库（APPLogger 附加 DB handler）
    log_service = LogService(repo)
    attach_application_db_logger(repo)

    # 组装服务
    services = {
        "document_service": document_service,
        "auth_service": auth_service,
        "session_service": session_service,
        "user_service": user_service,
        "history_service": history_service,
        "dashboard_service": dashboard_service,
        "request_log_service": request_log_service,
        "request_stats": request_stats,
        "database_service": database_service,
        "log_service": log_service,
        "tool_service": tool_service,
        "deliverable_service": deliverable_service,
        "chunk_parent_store": chunk_parent_store,
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
        services=services,
    )

    # ── Agent 引擎 + 问答用例（需要已装配完成的容器） ──
    system = IntegratedSystem(container)
    container.services["system"] = system
    container.services["query_service"] = QueryService(system)
    # 健康检查用例（只探各服务的 health 接口）
    container.services["health_service"] = HealthService()

    # ── Prompt 管理（identity / workflow / style；保存后热重载 SystemContext） ──
    from modules.prompt.service import PromptService
    container.services["prompt_service"] = PromptService(
        prompts_dir=prompts_dir,
        reloader=lambda: getattr(system.tool_loop.system_context, "reload", lambda: None)(),
    )

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
