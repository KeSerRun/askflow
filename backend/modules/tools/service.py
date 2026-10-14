"""modules.tools.service —— 工具定义（元数据 + handler 代码）的数据库用例。

- 首次启动把内建工具**种子**入 DB（幂等：已存在不覆盖，避免破坏管理员改动）；
- 运行时按 ``enabled`` 输出定义，交给 ``registry.load_defs`` 编译装载；
- 提供管理端增删改 / 启停接口。
"""

from __future__ import annotations

import importlib
import json
import os
import re
from datetime import datetime

from sqlalchemy import inspect as _sa_inspect
from sqlalchemy import text as _sa_text

from agent.tools.registry import BUILTIN_TOOLS, build_handler
from core.app_errors import InvalidInput, NotFound

from .entity import AgentTool

_CUSTOM_TOOLS_PKG = "custom_tools"
_MODULE_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

_UNSET = object()

_SEED_ORDER = {spec["name"]: i for i, spec in enumerate(BUILTIN_TOOLS)}


class ToolService:
    """工具定义的持久化用例。"""

    def __init__(self, repo: object, *, custom_tools_dir: str | None = None):
        """初始化。

        Args:
            repo: 通用仓储（collection="agent_tools"，返回 AgentTool 实体）。
            custom_tools_dir: 自定义工具源码目录（``custom_tools.{name}`` 模块从此目录加载）；
                为空则禁用自定义工具源码的上传 / 读取。
        """
        self._repo = repo
        self._custom_dir = (custom_tools_dir or "").rstrip("/\\")

    # ── 表结构 ──

    def _engine(self):
        """取底层 SQL 引擎（兼容裸 Repo / CachedRepo 包装）。"""
        raw = getattr(self._repo, "_repo", self._repo)
        return raw._engine

    def ensure_schema(self) -> None:
        """轻量迁移：旧库补 ``concurrent_safe``、清理 ``output_parameters``（幂等）。"""
        engine = self._engine()
        cols = {c["name"] for c in _sa_inspect(engine).get_columns("agent_tools")}
        with engine.begin() as conn:
            if "concurrent_safe" not in cols:
                conn.execute(_sa_text(
                    "ALTER TABLE agent_tools ADD COLUMN concurrent_safe BOOLEAN DEFAULT 0"
                ))
            if "call_count" not in cols:
                conn.execute(_sa_text(
                    "ALTER TABLE agent_tools ADD COLUMN call_count INTEGER DEFAULT 0"
                ))
            if "output_parameters" in cols:
                # SQLite 旧版不支持 DROP COLUMN：失败仅告警
                try:
                    conn.execute(_sa_text("ALTER TABLE agent_tools DROP COLUMN output_parameters"))
                except Exception as e:  # noqa: BLE001
                    from infra.util.logger import logger
                    logger.warning(f"清理 output_parameters 列失败（忽略，已不再使用）: {e}")

    # ── 种子 ──

    def seed_builtins(self) -> int:
        """把内建工具写入数据库（幂等）；返回本次新增条数。"""
        self.ensure_schema()
        count = 0
        now = datetime.now().isoformat(timespec="seconds")
        for spec in sorted(BUILTIN_TOOLS, key=lambda s: _SEED_ORDER[s["name"]]):
            name = spec["name"]
            rows = self._repo.find("agent_tools", {"name": name})
            if rows:
                # 迁移修复：内建行与声明不一致（模块/并发安全/参数 schema/描述）→ 同步为声明定义
                stale_module = (rows[0].handler_module or "") != (spec["module"] or "")
                stale_conc = (
                    bool(getattr(rows[0], "concurrent_safe", False))
                    != bool(spec.get("concurrent_safe", False))
                )
                stale_params = (rows[0].parameters or "") != json.dumps(spec["parameters"], ensure_ascii=False)
                stale_desc = (rows[0].description or "") != (spec["description"] or "")
                if stale_module or stale_conc or stale_params or stale_desc:
                    self._repo.update_where("agent_tools", {"name": name}, {
                        "description": spec["description"],
                        "parameters": json.dumps(spec["parameters"], ensure_ascii=False),
                        "code": spec["handler"],
                        "handler_module": spec["module"],
                        "concurrent_safe": spec.get("concurrent_safe", False),
                        "updated_at": now,
                    })
                continue
            self._repo.insert("agent_tools", AgentTool(
                name=name,
                description=spec["description"],
                parameters=json.dumps(spec["parameters"], ensure_ascii=False),
                code=spec["handler"],
                handler_module=spec["module"],
                enabled=True,
                concurrent_safe=bool(spec.get("concurrent_safe", False)),
                sort_order=_SEED_ORDER[name],
                updated_at=now,
            ))
            count += 1
        if count:
            from infra.util.logger import logger
            logger.info(f"内建工具已种子入数据库: 新增 {count} 个")
        return count

    def reset_builtins(self) -> dict:
        """把内建（系统）工具重置为 ``@tool`` 声明定义，覆盖管理员改动（幂等）。

        - 内建工具整行覆盖：description / parameters / code / handler_module /
          concurrent_safe / enabled / sort_order；
        - 缺失的内建工具补插入；
        - 自定义工具不受影响。

        Returns:
            ``{"updated", "inserted", "total"}``。
        """
        self.ensure_schema()
        if not BUILTIN_TOOLS:
            return {"updated": 0, "inserted": 0, "total": 0}
        now = datetime.now().isoformat(timespec="seconds")
        updated = inserted = 0
        for spec in BUILTIN_TOOLS:
            name = spec["name"]
            fields = {
                "description": spec["description"],
                "parameters": json.dumps(spec["parameters"], ensure_ascii=False),
                "code": spec["handler"],
                "handler_module": spec["module"],
                "concurrent_safe": bool(spec.get("concurrent_safe", False)),
                "enabled": True,
                "sort_order": _SEED_ORDER.get(name, 0),
                "call_count": 0,
                "updated_at": now,
            }
            if self._repo.find("agent_tools", {"name": name}):
                self._repo.update_where("agent_tools", {"name": name}, fields)
                updated += 1
            else:
                self._repo.insert("agent_tools", AgentTool(name=name, **fields))
                inserted += 1
        from infra.util.logger import logger
        logger.info(f"系统工具已重置: 更新 {updated} / 新增 {inserted} / 共 {len(BUILTIN_TOOLS)}")
        return {"updated": updated, "inserted": inserted, "total": len(BUILTIN_TOOLS)}

    # ── 查询 ──

    def list_all(self) -> list[dict]:
        rows = self._repo.find("agent_tools", order_by="sort_order")
        return [self._dump(r) for r in rows]

    def page_list(self, *, page: int = 1, page_size: int = 0,
                  keyword: str | None = None) -> dict:
        """管理端分页列工具（分页下推仓储层；``page_size<=0`` 表示全部；keyword 匹配名称/描述）。"""
        from core.pagination import paginate_query
        where = None
        kw = (keyword or "").strip()
        if kw:
            where = {"__or__": [
                {"name__icontains": kw},
                {"description__icontains": kw},
            ]}
        return paginate_query(
            self._repo, "agent_tools", where=where, order_by="sort_order",
            page=page, page_size=page_size, key="items", serialize=self._dump,
        )

    def list_enabled(self) -> list[dict]:
        rows = [r for r in self._repo.find("agent_tools") if getattr(r, "enabled", True)]
        rows.sort(key=lambda r: (r.sort_order or 0, r.id or 0))
        return [self._dump(r) for r in rows]

    def get(self, name: str) -> dict | None:
        rows = self._repo.find("agent_tools", {"name": name})
        return self._dump(rows[0]) if rows else None

    def runtime_defs(self) -> list[dict]:
        """输出给 ``registry.load_defs`` 的运行时定义（仅启用项）。"""
        out = []
        for d in self.list_enabled():
            try:
                params = json.loads(d["parameters"] or "{}")
            except ValueError:
                params = {"type": "object", "properties": {}}
            if not isinstance(params, dict):
                params = {"type": "object", "properties": {}}
            out.append({
                "name": d["name"],
                "description": d["description"],
                "parameters": params,
                "code": d["code"],
                "module": d["handler_module"],
                "concurrent_safe": d.get("concurrent_safe", False),
            })
        return out

    # ── 自定义工具源码（上传 .py → 落成 custom_tools 模块） ──

    def custom_tools_dir(self) -> str:
        """自定义工具源码目录：``template/custom_tools``。"""
        return self._custom_dir

    def save_custom_source(self, name: str, content: bytes) -> dict:
        """保存自定义工具源码：写入 ``custom_tools/{name}.py`` 并校验可作为模块加载。

        Raises:
            InvalidInput: 未配置目录 / 工具名非法 / 源码为空 / 模块加载失败或缺 handle。
        """
        if not self._custom_dir:
            raise InvalidInput("未配置存储数据目录，无法保存源码")
        name = (name or "").strip()
        if not _MODULE_NAME_RE.match(name):
            raise InvalidInput("工具名需为 Python 标识符（字母/数字/下划线）")
        if not content:
            raise InvalidInput("源码内容为空")
        d = self.custom_tools_dir()
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, f"{name}.py")
        with open(path, "wb") as f:
            f.write(content)
        try:
            mod = importlib.import_module(f"{_CUSTOM_TOOLS_PKG}.{name}")
            if not callable(getattr(mod, "handle", None)):
                raise InvalidInput("源码须定义 handle(args, ctx) 函数")
        except InvalidInput:
            os.remove(path)
            raise
        except Exception as e:  # noqa: BLE001
            os.remove(path)
            raise InvalidInput(f"源码无法作为模块加载: {e}") from e
        return {
            "code": content.decode("utf-8", errors="replace"),
            "module": f"{_CUSTOM_TOOLS_PKG}.{name}",
            "path": path,
        }

    def read_custom_source(self, name: str) -> str:
        """读取自定义工具源码文本（工具名 → ``custom_tools/{name}.py``）。

        Raises:
            NotFound: 文件不存在。
        """
        name = (name or "").strip()
        path = os.path.join(self.custom_tools_dir(), f"{name}.py") if self._custom_dir else ""
        if not path or not os.path.isfile(path):
            raise NotFound(f"自定义源码不存在: {name}.py")
        with open(path, encoding="utf-8") as f:
            return f.read()

    def delete_custom_source(self, name: str) -> None:
        """删除自定义源码文件（不存在则忽略）。"""
        name = (name or "").strip()
        if not self._custom_dir:
            return
        path = os.path.join(self.custom_tools_dir(), f"{name}.py")
        if os.path.isfile(path):
            os.remove(path)

    # ── 调用统计（agent_tools.call_count，响应式自增） ──

    def increment_call_count(self, name: str) -> None:
        """工具被调用一次：表内原子 ``call_count + 1``。"""
        if not name:
            return
        with self._engine().begin() as conn:
            conn.execute(
                _sa_text("UPDATE agent_tools SET call_count = call_count + 1 WHERE name = :n"),
                {"n": name},
            )

    def call_counts(self) -> dict[str, int]:
        """读取全部工具调用次数（仅返回大于 0 的；直接 SQL 读库，避免仓储缓存）。"""
        out: dict[str, int] = {}
        try:
            with self._engine().connect() as conn:
                rows = conn.execute(_sa_text(
                    "SELECT name, call_count FROM agent_tools")).fetchall()
        except Exception:  # noqa: BLE001
            return out
        for name, cnt in rows or []:
            cnt = int(cnt or 0)
            if cnt > 0:
                out[name] = cnt
        return out

    def reset_call_counts(self) -> dict:
        """重置所有工具调用次数为 0。"""
        with self._engine().begin() as conn:
            conn.execute(_sa_text("UPDATE agent_tools SET call_count = 0"))
        return {"message": "所有工具调用次数已重置"}

    # ── 增删改 ──

    def create(self, *, name: str, description: str, parameters: dict,
               code: str, handler_module: str | None = None,
               enabled: bool = True, concurrent_safe: bool = False) -> dict:
        """新增工具（写入前预编译 handler 代码校验）。

        Raises:
            InvalidInput: 名称/代码为空、代码编译失败、名称已存在。
        """
        name = (name or "").strip()
        code = (code or "").strip()
        if not name:
            raise InvalidInput("工具名称不能为空")
        if not code:
            raise InvalidInput("工具 handler 代码不能为空")
        if self._repo.find("agent_tools", {"name": name}):
            raise InvalidInput(f"工具 {name} 已存在")
        try:
            build_handler(code, handler_module)
        except Exception as e:
            raise InvalidInput(f"handler 代码编译失败: {e}")

        self._repo.insert("agent_tools", AgentTool(
            name=name,
            description=description or "",
            parameters=json.dumps(parameters or {}, ensure_ascii=False),
            code=code,
            handler_module=handler_module,
            enabled=bool(enabled),
            concurrent_safe=bool(concurrent_safe),
            sort_order=0,
            updated_at=datetime.now().isoformat(timespec="seconds"),
        ))
        return self.get(name)

    def update(self, name: str, *, description=_UNSET, parameters=_UNSET,
               code=_UNSET, handler_module=_UNSET, enabled=_UNSET,
               concurrent_safe=_UNSET, sort_order=_UNSET) -> dict:
        """更新工具（未提供的字段保持不变）。

        Raises:
            NotFound: 工具不存在。
            InvalidInput: 新代码编译失败。
        """
        rows = self._repo.find("agent_tools", {"name": name})
        if not rows:
            raise NotFound(f"工具 {name} 不存在")
        old = rows[0]

        changes: dict = {}
        if description is not _UNSET:
            changes["description"] = description or ""
        if parameters is not _UNSET:
            changes["parameters"] = json.dumps(parameters or {}, ensure_ascii=False)
        if code is not _UNSET:
            changes["code"] = (code or "").strip()
            changes["updated_at"] = datetime.now().isoformat(timespec="seconds")
            try:
                build_handler(changes["code"], old.handler_module if handler_module is _UNSET else handler_module)
            except Exception as e:
                raise InvalidInput(f"handler 代码编译失败: {e}")
        if handler_module is not _UNSET:
            changes["handler_module"] = handler_module
        if enabled is not _UNSET:
            changes["enabled"] = bool(enabled)
        if concurrent_safe is not _UNSET:
            changes["concurrent_safe"] = bool(concurrent_safe)
        if sort_order is not _UNSET:
            changes["sort_order"] = int(sort_order or 0)

        if not changes:
            return self.get(name)
        changes.setdefault("updated_at", datetime.now().isoformat(timespec="seconds"))
        self._repo.update_where("agent_tools", {"name": name}, changes)
        return self.get(name)

    def remove(self, name: str) -> None:
        """删除工具（连同自定义源码文件）。"""
        self._repo.delete_where("agent_tools", {"name": name})
        self.delete_custom_source(name)

    # ── 序列化 ──

    @staticmethod
    def _dump(r) -> dict:
        return {
            "id": getattr(r, "id", None),
            "name": r.name,
            "description": r.description,
            "parameters": r.parameters,          # JSON 文本（前端编辑用）
            "code": r.code,                       # handler 源码
            "handler_module": r.handler_module,
            "enabled": bool(getattr(r, "enabled", True)),
            "concurrent_safe": bool(getattr(r, "concurrent_safe", False)),
            "sort_order": getattr(r, "sort_order", 0) or 0,
            "call_count": int(getattr(r, "call_count", 0) or 0),
            "updated_at": r.updated_at,
        }
