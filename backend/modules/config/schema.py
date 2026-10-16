"""modules.config.schema —— 配置表单 schema（由 AppConfig 自动派生）。

- ``key`` = **环境变量名**（如 ``LLM_MODEL``）——与 `.env`、前端提交一致；
- ``group`` = 由变量名组前缀派生的中文分组（前端据此分块）；
- 类型由 AppConfig 字段类型推断；枚举字段附加 ``options``（下拉），
  list 字段标记 ``textarea``（多行），避免全部渲染成单行输入框。
"""

from __future__ import annotations

from dataclasses import fields
from typing import get_args, get_type_hints

from config import FIELD_TO_ENV
from config.app_config import AppConfig

# 组前缀 → 中文分组名（用于前端分块）
GROUP_LABELS = {
    "LLM": "对话模型",
    "EMBED": "嵌入模型",
    "MINERU": "MinerU 解析",
    "STORAGE": "存储 / 数据库",
    "RETRIEVAL": "检索",
    "VECTOR": "向量库",
    "OBJECT": "对象存储",
    "REDIS": "Redis",
    "CACHE": "缓存",
    "AGENT": "Agent",
    "CONTEXT": "上下文治理",
    "SEARCH": "联网搜索",
    "LOG": "日志",
    "AUTH": "认证 / 超级用户",
    "UPLOAD": "上传限制",
    "WEB": "前端",
}

# env 名 → 中文显示名（配置表单 label）。覆盖全部 AppConfig 字段。
LABEL_MAP: dict[str, str] = {
    # LLM
    "LLM_API_KEY": "对话模型 API Key",
    "LLM_BASE_URL": "对话模型 API 地址",
    "LLM_MODEL": "对话模型名称",
    "LLM_REASONING_EFFORT": "推理力度（low/medium/high）",
    "LLM_TEMPERATURE": "采样温度（越低越稳定）",
    "LLM_TIMEOUT": "LLM 请求超时（秒）",
    "LLM_MAX_RETRIES": "LLM 最大重试次数",
    "LLM_HEALTH_URL": "LLM 健康检查地址",
    # EMBED
    "EMBED_API_KEY": "嵌入模型 API Key",
    "EMBED_BASE_URL": "嵌入模型 API 地址",
    "EMBED_MODEL": "嵌入模型名称",
    "EMBED_DIM": "嵌入向量维度",
    "EMBED_HEALTH_URL": "嵌入健康检查地址",
    # MINERU
    "MINERU_API_KEY": "MinerU API Key",
    "MINERU_BASE_URL": "MinerU API 地址",
    "MINERU_TIER": "解析档位",
    "MINERU_MAX_CONCURRENCY": "最大解析并发数",
    "MINERU_HEALTH_URL": "MinerU 健康检查地址",
    # STORAGE
    "STORAGE_DATA_DIR": "数据根目录",
    "STORAGE_BACKEND": "存储后端",
    "STORAGE_DB_URL": "数据库连接串",
    # RETRIEVAL
    "RETRIEVAL_TOP_K": "检索返回条数 top_k",
    "RETRIEVAL_MIN_CHUNK": "最小切块字符数",
    "RETRIEVAL_STOP_WORDS": "检索停用词（逗号分隔）",
    # VECTOR / OBJECT
    "VECTOR_MILVUS_URI": "Milvus 连接地址",
    "VECTOR_MILVUS_TOKEN": "Milvus 鉴权 Token",
    "VECTOR_MILVUS_COLLECTION": "Milvus 集合名",
    "OBJECT_MINIO_ENDPOINT": "MinIO 地址",
    "OBJECT_MINIO_ACCESS_KEY": "MinIO Access Key",
    "OBJECT_MINIO_SECRET_KEY": "MinIO Secret Key",
    "OBJECT_MINIO_BUCKET": "MinIO 存储桶",
    "OBJECT_MINIO_SECURE": "MinIO 使用 HTTPS",
    # CACHE / REDIS
    "CACHE_BACKEND": "缓存后端",
    "REDIS_URL": "Redis 连接地址",
    # AGENT
    "AGENT_MAX_TOOL_ITER": "工具调用最大迭代次数",
    "AGENT_MAX_OUTPUT_TOKENS": "单次输出最大 token 数",
    "AGENT_CHECKPOINT_ENABLED": "启用 Agent 检查点",
    # CONTEXT
    "CONTEXT_WINDOW_TOKENS": "上下文窗口 token 数",
    "CONTEXT_INPUT_RATIO": "输入占比",
    "CONTEXT_COMPRESSION_RATIO": "压缩比例",
    "CONTEXT_TOOL_PAGE_CHARS": "工具分页读取字符数",
    # SEARCH
    "SEARCH_SEARXNG_URL": "SearXNG 搜索服务地址",
    "SEARCH_TIMEOUT": "搜索超时（秒）",
    # LOG
    "APP_ENV": "运行环境",
    "LOG_PATH": "日志目录",
    "LOG_APP_LEVEL": "应用日志级别",
    "LOG_HTTP_LEVEL": "HTTP 日志级别",
    "LOG_CONSOLE_LEVEL": "控制台日志级别",
    "LOG_MAX_MB": "单个日志文件上限（MB）",
    "LOG_BACKUP_COUNT": "日志备份数量",
    # AUTH
    "AUTH_SUPERUSER_USERS": "超级用户名（逗号分隔）",
    "AUTH_SUPERUSER_PASSWORDS": "超级用户密码（逗号分隔）",
    "AUTH_JWT_SECRET": "JWT 密钥",
    # UPLOAD
    "UPLOAD_MAX_SESSION_MB": "会话上传上限（MB）",
    # 并发
    "APP_THREAD_POOL": "HTTP 线程池上限",
    "APP_WORKERS": "进程数（>1 按进程隔离）",
    # WEB
    "WEB_DIST_DIR": "前端构建目录",
    "WEB_ASSETS_DIR": "前端资源目录",
    "WEB_INDEX_FILE": "前端入口文件",
}

# 健康检查地址（MILVUS / MINIO / LLM / EMBED / MINERU 已在上面覆盖）
LABEL_MAP.update({
    "MILVUS_HEALTH_URL": "Milvus 健康检查地址",
    "MINIO_HEALTH_URL": "MinIO 健康检查地址",
})

_HINTS = get_type_hints(AppConfig)
_TYPE_MAP = {list: "string", str: "string", bool: "bool", int: "int", float: "float"}

# 枚举（env 名 → 可选项列表）——前端渲染为下拉
_ENUM_OPTIONS: dict[str, list[dict]] = {
    "STORAGE_BACKEND": [
        {"value": "sqlite", "label": "SQLite（本地文件，默认）"},
        {"value": "mysql", "label": "MySQL（多实例/容器部署）"},
    ],
    "CACHE_BACKEND": [
        {"value": "inprocess", "label": "进程内缓存（单实例，默认）"},
        {"value": "redis", "label": "Redis（多实例共享缓存）"},
    ],
    "APP_ENV": [
        {"value": "development", "label": "开发"},
        {"value": "production", "label": "生产"},
    ],
    "MINERU_TIER": [
        {"value": "flash", "label": "flash（最快）"},
        {"value": "basic", "label": "basic（默认，CPU 友好）"},
        {"value": "standard", "label": "standard（质量更高，需更多内存）"},
    ],
}

# 多行文本（env 名 → True）——列表/长内容字段渲染为 textarea
_TEXTAREAS = {
    "RETRIEVAL_STOP_WORDS": True,
    "AUTH_SUPERUSER_USERS": True,
    "AUTH_SUPERUSER_PASSWORDS": True,
}


def _infer_type(name: str) -> str:
    """按 AppConfig 字段类型推断控件类型。"""
    tp = _HINTS.get(name)
    args = get_args(tp)
    if args:  # Optional[X] / X | None → 取非 None 分支
        tp = next((a for a in args if a is not type(None)), tp)
    return _TYPE_MAP.get(tp, "string")


def _group_of(env_name: str) -> str:
    """由变量名组前缀取中文分组名（未知则用前缀本身）。"""
    prefix = env_name.split("_", 1)[0]
    return GROUP_LABELS.get(prefix, prefix)


def build_schema() -> list[dict]:
    """从 AppConfig 自动生成表单 schema（key=env 名，group=分组）。"""
    items: list[dict] = []
    for f in fields(AppConfig):
        env_name = FIELD_TO_ENV.get(f.name)
        if not env_name:
            continue
        item = {
            "key": env_name,
            "label": LABEL_MAP.get(env_name, env_name),
            "group": _group_of(env_name),
            "type": _infer_type(f.name),
        }
        if env_name in _ENUM_OPTIONS:
            item["type"] = "select"
            item["options"] = _ENUM_OPTIONS[env_name]
        if _TEXTAREAS.get(env_name):
            item["type"] = "string"
            item["textarea"] = True
        items.append(item)
    order = {g: i for i, g in enumerate(GROUP_LABELS.values())}
    items.sort(key=lambda x: order.get(x["group"], len(order)))
    return items
