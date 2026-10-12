"""日志系统：应用日志 / HTTP 请求日志 / LLM 输入记录。

控制台输出带 ANSI 颜色：DEBUG=青色, INFO=绿色, WARNING=黄色, ERROR=红色。
文件输出带滚动窗口（RotatingFileHandler），超出大小自动轮转，保留最近 N 个备份。
"""
import json as _json
import logging
import logging.handlers
import os
import re
from config import conf


# ── ANSI 颜色常量 ──────────────────────────────────
_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_COLORS = {
    logging.DEBUG:    "\033[36m",      # 青色
    logging.INFO:     "\033[32m",      # 绿色
    logging.WARNING:  "\033[33m",      # 黄色
    logging.ERROR:    "\033[31m",      # 红色
    logging.CRITICAL: "\033[1;31m",    # 加粗红色
}


# ── 日志格式（实现常量，非用户配置） ──
_LOG_FILE_FORMAT = "%(asctime)s | %(levelname)-5s | %(module)s:%(lineno)d | %(message)s"
_LOG_CONSOLE_FORMAT = "%(levelname)-5s %(module)s:%(lineno)d | %(message)s"


class ColorFormatter(logging.Formatter):
    """带 ANSI 颜色的日志格式化器。

    控制台输出：级别名着色、模块名加粗、消息中的 URL 自动加粗。
    文件 Handler 不受影响（使用普通 Formatter）。
    """

    # URL 模式：http/https/ftp 开头的链接
    _URL_RE = re.compile(r'(https?://[^\s,，。；;]+)')

    def format(self, record: logging.LogRecord) -> str:
        color = _COLORS.get(record.levelno, "")
        orig_levelname = record.levelname
        orig_module = record.module
        orig_msg = record.msg
        # URL 加粗（仅对字符串消息，避免破坏格式化参数）
        if isinstance(record.msg, str):
            record.msg = self._URL_RE.sub(f'{_BOLD}\\1{_RESET}', record.msg)
        try:
            record.levelname = f"{color}{_BOLD}{record.levelname}{_RESET}"
            record.module = f"{_BOLD}{record.module}{_RESET}"
            return super().format(record)
        finally:
            record.levelname = orig_levelname
            record.module = orig_module
            record.msg = orig_msg


# ── 滚动窗口文件 Handler 工厂 ─────────────────────
def _rotating_handler(
    filename: str,
    level: int,
    fmt: logging.Formatter,
    max_mb: int,
    backup_count: int,
) -> logging.handlers.RotatingFileHandler:
    """创建一个带滚动窗口的文件 Handler。

    Args:
        filename: 日志文件路径（相对于 log_path）。
        level: 日志级别。
        fmt: Formatter 实例。
        max_mb: 单文件最大大小（MB）。
        backup_count: 保留的备份文件数。

    Returns:
        RotatingFileHandler 实例。
    """
    path = os.path.join(conf.log_path, filename)
    h = logging.handlers.RotatingFileHandler(
        path, encoding="utf-8",
        maxBytes=max_mb * 1024 * 1024, backupCount=backup_count,
    )
    h.setLevel(level)
    h.setFormatter(fmt)
    return h


# ── 应用日志器 ────────────────────────────────────
os.makedirs(conf.log_path, exist_ok=True)

# ── 环境分级 ──────────────────────────────────────
# production（生产）：应用/控制台/HTTP 日志只保留 ERROR 及以上，且不落 LLM 输入日志。
_APP_ENV = str(getattr(conf, "app_env", "") or "").strip().lower()
_IS_PROD = _APP_ENV in ("production", "prod")


def _level(name) -> int:
    text = str(name or "").strip()
    return logging.getLevelName(text.upper()) if text else logging.INFO


_app_level = "ERROR" if _IS_PROD else (conf.log_app_level or "INFO")
_console_level = "ERROR" if _IS_PROD else (conf.log_console_level or "DEBUG")
_http_level = "ERROR" if _IS_PROD else (conf.log_http_level or "INFO")

# ── 应用日志器 ────────────────────────────────────
logger = logging.getLogger("APPLogger")
logger.setLevel(logging.DEBUG)

# 文件 handler：带滚动窗口
_fh = _rotating_handler(
    "app.log", _app_level,
    logging.Formatter(_LOG_FILE_FORMAT),
    conf.log_max_mb, conf.log_backup_count,
)
# 控制台 handler：带颜色
_ch = logging.StreamHandler()
_ch.setLevel(_console_level)
_ch.setFormatter(ColorFormatter(_LOG_CONSOLE_FORMAT))

logger.addHandler(_fh)
logger.addHandler(_ch)


# ── LLM 输入日志（生产不落盘，避免敏感输入入库） ──
_llm_logger = logging.getLogger("LLMInputLogger")
_llm_logger.setLevel(logging.CRITICAL if _IS_PROD else logging.INFO)
_llm_logger.propagate = False
_lh = _rotating_handler(
    "input.log", logging.CRITICAL if _IS_PROD else logging.INFO,
    logging.Formatter(
        "=== %(asctime)s %(message)s ===\n%(msg_json)s\n",
        datefmt="%Y-%m-%dT%H:%M:%S",
    ),
    conf.log_max_mb, conf.log_backup_count,
)
_llm_logger.addHandler(_lh)


# ── HTTP 请求日志器 ──────────────────────────────
_http_logger = logging.getLogger("HTTPLogger")
_http_logger.setLevel(_http_level)
_http_logger.propagate = False
_hh = _rotating_handler(
    "http.log", _http_level,
    logging.Formatter(
        "[%(asctime)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S",
    ),
    conf.log_max_mb, conf.log_backup_count,
)
_http_logger.addHandler(_hh)


# ── 公共日志接口 ────────────────────────────────
def log_http(method: str, path: str, status: int, username: str = "-",
             request_id: str = "", elapsed_ms: int | None = None):
    """记录 HTTP 请求日志（可带 request_id / 耗时，便于链路追踪）。"""
    rid = f"[{request_id[:8]}] " if request_id else ""
    cost = f"{elapsed_ms:>5}ms  " if elapsed_ms is not None else ""
    _http_logger.info(f"{rid}{method:6s} {status}  {cost}{username:12s}  {path}")


def log_llm_input(messages: list, round: int = 0, suffix: str = ""):
    """记录 LLM 输入消息到 input.log。"""
    try:
        tag = f" round={round}{suffix}" if suffix else f" round={round}"
        _llm_logger.info(
            tag,
            extra={"msg_json": _json.dumps(messages, ensure_ascii=False, indent=2)},
        )
    except Exception:
        pass


# ── Uvicorn / FastAPI 日志彩色化 ────────────────────


def configure_third_party_logging():
    """将 ColorFormatter 注入 uvicorn / FastAPI 等已存在的 StreamHandler。

    应用启动（lifespan）时调用一次：uvicorn 会先套用其默认日志配置，
    此处遍历其 ``StreamHandler`` 并替换为 ``ColorFormatter``，统一格式与颜色。
    """
    _targets = ("uvicorn", "uvicorn.error", "uvicorn.access", "fastapi")
    for name in _targets:
        lg = logging.getLogger(name)
        for h in lg.handlers:
            if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler):
                h.setFormatter(ColorFormatter(_LOG_CONSOLE_FORMAT))