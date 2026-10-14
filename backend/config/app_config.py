"""config.app_config —— 配置层单模块：AppConfig + 命名约定 + 加载 + conf 门面。

约定：AppConfig 字段名 = 环境变量名小写（如 llm_model ↔ LLM_MODEL）。

- AppConfig：不可变配置对象（字段无代码默认值）；
- FIELD_TO_ENV / ENV_TO_FIELD：按约定推导；
- load_app_config()：取值链 系统环境变量 > .env > .env.default；
- conf：全局门面（conf.x → AppConfig）；后台改配置由 write_env 写回 .env。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, fields
from typing import get_args, get_type_hints

from ._utils import (
    _load_dotenv,
    _strip_quotes,
    _to_bool,
    _to_env_text,
    _unwrap_optional,
    normalize_path,
)
from .paths import _dotenv_file, _env_default_file


@dataclass(frozen=True)
class AppConfig:
    """应用运行配置（构建后不可变，字段无默认值）。"""

    # ── 存储 ──
    storage_data_dir: str
    storage_backend: str

    # ── 检索 ──
    retrieval_top_k: int
    retrieval_min_chunk: int
    retrieval_stop_words: list

    # ── 日志 ──
    app_env: str
    log_path: str
    log_app_level: str
    log_http_level: str
    log_console_level: str
    log_max_mb: int
    log_backup_count: int

    # ── LLM / API ──
    llm_api_key: str | None
    llm_base_url: str
    llm_model: str
    llm_reasoning_effort: str | None
    llm_temperature: float
    llm_timeout: float
    llm_max_retries: int
    llm_health_url: str | None
    milvus_health_url: str | None
    minio_health_url: str | None
    embed_api_key: str | None
    embed_base_url: str
    embed_model: str
    embed_dim: int
    embed_health_url: str | None

    # ── 治理 ──
    context_window_chars: int
    context_input_ratio: float
    context_compression_ratio: float
    context_tool_page_chars: int

    # ── 搜索（SearXNG） ──
    search_searxng_url: str | None
    search_timeout: float

    # ── Agent ──
    agent_max_tool_iter: int
    agent_max_output_chars: int
    agent_checkpoint_enabled: bool

    # ── 并发调优 ──
    app_thread_pool: int      # FastAPI 同步接口线程池上限
    app_workers: int          # uvicorn 进程数（>1 时内存态按进程隔离）

    # ── 超级用户 ──
    auth_superuser_users: list
    auth_superuser_passwords: list

    # ── MinerU ──
    mineru_base_url: str
    mineru_api_key: str | None
    mineru_max_concurrency: int
    # 本地解析档位（4.0 tier）：flash / basic / standard
    mineru_tier: str
    mineru_health_url: str | None

    # ── 上传 ──
    upload_max_session_mb: int

    # ── 基础设施（后端开关） ──
    storage_db_url: str
    vector_milvus_uri: str
    vector_milvus_token: str | None
    vector_milvus_collection: str
    object_minio_endpoint: str
    object_minio_access_key: str | None
    object_minio_secret_key: str | None
    object_minio_bucket: str
    object_minio_secure: bool
    cache_backend: str
    redis_url: str

    # ── 运行时 ──
    auth_jwt_secret: str
    web_dist_dir: str
    web_assets_dir: str
    web_index_file: str


# 命名约定映射（env 名 = 字段名大写）
FIELD_TO_ENV: dict[str, str] = {f.name: f.name.upper() for f in fields(AppConfig)}
ENV_TO_FIELD: dict[str, str] = {v: k for k, v in FIELD_TO_ENV.items()}

# 需按路径归一的字段（相对 backend/ → 绝对路径）
_PATH_FIELDS = frozenset({
    "storage_data_dir", "log_path",
    "web_dist_dir", "web_assets_dir", "web_index_file",
})
# 需转小写的字段
_LOWER_FIELDS = frozenset({"storage_backend", "cache_backend"})
# 类型 → _get 的转换参数（int/float/bool/list）；其余按 str 处理
_CAST_KWARGS = {
    int: {"cast": int},
    float: {"cast": float},
    bool: {"cast": _to_bool},
    list: {"split": ","},
}


# 从环境加载
def _resolve_jwt(raw_env: dict, raw_dotenv: dict) -> str:
    """读取 JWT 密钥；缺失则生成并写入 .env（保持重启稳定）。"""
    key = raw_env.get("AUTH_JWT_SECRET") or raw_dotenv.get("AUTH_JWT_SECRET")
    if key:
        return key
    import secrets
    key = secrets.token_hex(32)
    try:
        with open(_dotenv_file, "a", encoding="utf-8") as f:
            f.write(f"\n# 自动生成的 JWT 密钥（如要更换请删除此行）\nAUTH_JWT_SECRET={key}\n")
    except Exception:
        pass
    return key


def load_app_config() -> AppConfig:
    """从环境变量构建 AppConfig（无代码默认值）。

    Returns:
        AppConfig: 不可变配置对象。
    """
    raw_env = dict(os.environ)
    # 默认基线（.env.default）+ 用户覆盖（.env）
    raw_dotenv = {**_load_dotenv(_env_default_file), **_load_dotenv(_dotenv_file)}

    def _get(field, cast=None, split=None):
        """读取配置：系统环境变量 > .env > .env.default。

        约定：值 "none"（不区分大小写）表示留空/未设置，等同缺失。
        返回形态：split → 列表；缺失/空 → ""；cast 失败 → None。

        参数 ``field`` 为 AppConfig 字段名，环境变量名按其大写推导（约定）。
        """
        env_key = field.upper()  # 约定：env 名 = 字段名大写
        # 1 取值（系统环境变量优先）
        value = raw_env.get(env_key)
        if value is None:
            value = raw_dotenv.get(env_key)
        # 2 清理：去首尾引号；字面量 "none" 视为未设置
        if value is not None:
            value = _strip_quotes(value)
            if value.strip().lower() == "none":
                value = None
        # 3 形态转换：列表 → 类型 → 原样（空则返回 ""）
        if split is not None:
            return [w.strip() for w in (value or "").split(split) if w.strip()]
        if cast is not None and value not in (None, ""):
            try:
                return cast(value)
            except (TypeError, ValueError):
                return None
        return value if value else ""

    hints = get_type_hints(AppConfig)
    kwargs: dict = {}
    for f in fields(AppConfig):
        name = f.name
        if name == "auth_jwt_secret":               # 特例：缺失则生成并写回 .env
            kwargs[name] = _resolve_jwt(raw_env, raw_dotenv)
            continue
        tp = hints.get(name)
        base = _unwrap_optional(tp)
        is_optional = type(None) in get_args(tp)
        if name in _PATH_FIELDS:
            kwargs[name] = normalize_path(_get(name))
        elif base in _CAST_KWARGS:
            kwargs[name] = _get(name, **_CAST_KWARGS[base])
        else:  # str / str | None
            val = _get(name)
            if name in _LOWER_FIELDS:
                val = (val or "").lower()
            kwargs[name] = (val or None) if is_optional else val

    cfg = AppConfig(**kwargs)
    return cfg


# 全局门面
class Config:
    """全局配置对象：延迟委托 AppConfig（首次访问时加载 .env）。"""

    def __init__(self):
        self._cfg = None

    def _ensure(self) -> None:
        if self._cfg is None:
            self._cfg = load_app_config()

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        self._ensure()
        return getattr(self._cfg, name)


# ── 全局单例 ──

conf = Config()


# ── 后台配置读写（.env 单源） ──

def config_env_dict() -> dict:
    """导出当前配置为 ``{env 名: 值}``（后台展示/编辑用，key 与表单对齐）。

    路径类字段（``_PATH_FIELDS``）回显**原始配置值**（如 ``../frontend/dist``），
    而非标准化后的绝对路径——避免管理后台保存时把宿主绝对路径写回 ``.env``。
    """
    cfg = load_app_config()
    raw_env = dict(os.environ)
    raw_dotenv = {**_load_dotenv(_env_default_file), **_load_dotenv(_dotenv_file)}
    out: dict = {}

    def _raw(field: str) -> str:
        """读取环境链中的原始值（不归一化），"none"/缺失返回空串。"""
        key = field.upper()
        v = raw_env.get(key)
        if v is None:
            v = raw_dotenv.get(key)
        if not v:
            return ""
        v = _strip_quotes(v)
        return "" if v.strip().lower() == "none" else v

    for field, env_name in FIELD_TO_ENV.items():
        if field in _PATH_FIELDS:
            val = _raw(field)
        else:
            try:
                val = getattr(cfg, field)
            except AttributeError:
                continue
        if isinstance(val, (str, int, float, bool, list)):
            out[env_name] = val
    return out


def write_env(updates: dict) -> bool:
    """把 ``{env 名: 值}`` 写回 `.env`（行级替换/追加）；返回是否有写入。"""
    lines: list[str] = []
    if os.path.exists(_dotenv_file):
        with open(_dotenv_file, encoding="utf-8") as f:
            lines = f.readlines()
    changed = False
    for env_name, val in (updates or {}).items():
        if env_name not in ENV_TO_FIELD:
            continue
        text = _to_env_text(val)
        replaced = False
        for i, line in enumerate(lines):
            stripped = line.lstrip()
            if stripped.startswith(env_name + "="):
                indent = line[: len(line) - len(stripped)]
                lines[i] = f"{indent}{env_name}={text}\n"
                replaced = True
                changed = True
                break
        if not replaced:
            lines.append(f"{env_name}={text}\n")
            changed = True
    if not changed:
        return False
    with open(_dotenv_file, "w", encoding="utf-8") as f:
        f.writelines(lines)
    return True
