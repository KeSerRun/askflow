"""modules.deliverable.service —— 交付物用例。

职责：
- **模板管理**：``template/deliverable/{name}.json``（启动写入内置 3 套，之后可被后台增删改）；
- **渲染**：Jinja2 渲染模板 HTML → PyMuPDF Story 渲成 PDF；
- **生成+存储**：PDF 写对象存储 ``deliverables/{user}/{session}/{id}.pdf``，元信息落 ``deliverables`` 表；
- **读取**：按会话列出 / 按 id 取回 PDF 字节。
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import date, datetime
from pathlib import Path

from jinja2 import BaseLoader, Environment, TemplateError

from core.app_errors import InvalidInput, NotFound, PermissionDenied
from infra.util.logger import logger

from .entity import Deliverable
from .markdown import md_filter
from .renderer import render_html_to_pdf
from .templates import BUILTIN_TEMPLATES, SAMPLE_CONTENT

_COLLECTION = "deliverables"
_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class DeliverableService:
    """交付物：模板管理 + 渲染 + 生成 + 读取。"""

    def __init__(self, repo: object, object_store: object | None, templates_dir: str):
        """初始化。

        Args:
            repo: 通用仓储（写/读 ``deliverables`` 表）。
            object_store: 对象存储适配器（``put_bytes`` / ``get_bytes``）；None 表示不可用。
            templates_dir: 模板 JSON 目录。
        """
        self._repo = repo
        self._os = object_store
        self._dir = Path(templates_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._env = Environment(loader=BaseLoader(), autoescape=True, trim_blocks=True, lstrip_blocks=True)
        self._env.filters["md"] = md_filter
        self._seed_builtins()

    # ── 模板管理 ──

    def _seed_builtins(self) -> None:
        """写入/升级内置模板；被人工编辑过的模板不动（按内容指纹判断）。"""
        for t in BUILTIN_TEMPLATES:
            p = self._dir / f"{t['name']}.json"
            if not p.exists():
                self._write_builtin(p, t)
                continue
            try:
                cur = json.loads(p.read_text(encoding="utf-8"))
            except Exception as e:  # noqa: BLE001
                logger.warning(f"模板 {p.name} 解析失败，跳过种子: {e}")
                continue
            recorded = cur.get("builtin_hash")
            if recorded is not None and recorded != self._payload_hash(cur):
                continue  # 已被人工编辑 → 保留
            if int(cur.get("version") or 0) < int(t.get("version") or 1):
                self._write_builtin(p, t)
                logger.info(f"内置交付物模板已升级: {t['name']} → v{t.get('version') or 1}")

    @staticmethod
    def _payload_hash(data: dict) -> str:
        """模板「内容」指纹（不含 name/version/builtin_hash），用于判断是否被人工改过。"""
        payload = {k: data.get(k) for k in ("label", "description", "fields", "html")}
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        return hashlib.md5(raw.encode("utf-8")).hexdigest()

    def _write_builtin(self, p: Path, builtin: dict) -> None:
        """内置模板落盘（附 version 与内容指纹，供后续安全升级）。"""
        data = dict(builtin)
        data["version"] = int(builtin.get("version") or 1)
        data["builtin_hash"] = self._payload_hash(builtin)
        self._write(p, data)

    def _path(self, name: str) -> Path:
        if not _NAME_RE.match(str(name or "")):
            raise InvalidInput("非法的模板名（仅字母/数字/下划线/连字符）")
        return self._dir / f"{name}.json"

    @staticmethod
    def _write(p: Path, data: dict) -> None:
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def list_templates(self) -> list[dict]:
        """列出模板元信息（不含 HTML）：name / label / description / fields。"""
        out = []
        for f in sorted(self._dir.glob("*.json")):
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
            except Exception as e:  # noqa: BLE001
                logger.warning(f"模板 {f.name} 解析失败: {e}")
                continue
            out.append(
                {
                    "name": d.get("name") or f.stem,
                    "label": d.get("label") or f.stem,
                    "description": d.get("description") or "",
                    "fields": d.get("fields") or [],
                }
            )
        return out

    def get_template(self, name: str) -> dict:
        """读取完整模板（含 HTML）。"""
        p = self._path(name)
        if not p.exists():
            raise NotFound(f"模板不存在: {name}")
        return json.loads(p.read_text(encoding="utf-8"))

    def save_template(self, name: str, payload: dict) -> dict:
        """新增 / 更新模板（name 为标识，payload 含 label/description/fields/html）。"""
        p = self._path(name)
        html = (payload.get("html") or "").strip()
        if not html:
            raise InvalidInput("模板 HTML 不能为空")
        try:
            self._env.from_string(html)
        except TemplateError as e:
            raise InvalidInput(f"模板语法错误: {e}")
        data = {
            "name": name,
            "label": (payload.get("label") or name).strip(),
            "description": (payload.get("description") or "").strip(),
            "accent": (payload.get("accent") or "").strip(),
            "css": payload.get("css") or "",
            "fields": payload.get("fields") or [],
            "html": html,
        }
        # 保留内置标记：人工保存后内容指纹不再匹配 → 之后不再被内置升级覆盖
        old = {}
        if p.exists():
            try:
                old = json.loads(p.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                old = {}
        if old.get("version") is not None:
            data["version"] = old["version"]
        if old.get("builtin_hash"):
            data["builtin_hash"] = old["builtin_hash"]
        self._write(p, data)
        logger.info(f"交付物模板已保存: {name}")
        return data

    def reset_templates(self) -> list[str]:
        """把内置模板恢复为代码内置版本（会覆盖对内置模板的人工改动）。"""
        restored = []
        for t in BUILTIN_TEMPLATES:
            self._write_builtin(self._dir / f"{t['name']}.json", t)
            restored.append(t["name"])
        logger.info(f"内置交付物模板已重置: {restored}")
        return restored

    def delete_template(self, name: str) -> dict:
        """删除模板。"""
        p = self._path(name)
        if not p.exists():
            raise NotFound(f"模板不存在: {name}")
        p.unlink()
        logger.info(f"交付物模板已删除: {name}")
        return {"name": name}

    # ── 渲染 / 生成 ──

    def _render(self, template_name: str, title: str, content: dict) -> bytes:
        tpl = self.get_template(template_name)
        try:
            html = self._env.from_string(tpl.get("html") or "").render(
                title=title or "",
                content=content or {},
                today=date.today().isoformat(),
            )
        except TemplateError as e:
            raise InvalidInput(f"模板渲染失败: {e}")
        return render_html_to_pdf(
            html,
            css=tpl.get("css") or "",
            accent=tpl.get("accent") or "",
            footer=title or "",
        )

    def preview(self, template_name: str) -> bytes:
        """用样例内容渲染预览 PDF（管理端）。"""
        tpl = self.get_template(template_name)
        sample = SAMPLE_CONTENT.get(template_name) or {}
        return self._render(template_name, f"{tpl.get('label') or template_name}（预览）", sample)

    def create(self, *, user_id: int, session_id: str, template: str, title: str, content: dict) -> dict:
        """渲染并生成一份交付物（存对象存储 + 落库），返回元信息。"""
        if self._os is None:
            raise RuntimeError("对象存储不可用，无法生成交付物")
        title = (title or "").strip() or "交付物"
        pdf = self._render(template, title, content)
        did = uuid.uuid4().hex
        key = f"deliverables/{int(user_id)}/{session_id}/{did}.pdf"
        self._os.put_bytes(key, pdf, content_type="application/pdf")
        row = Deliverable(
            id=did,
            user_id=int(user_id),
            session_id=session_id,
            template=template,
            title=title,
            object_key=key,
            size=len(pdf),
            created_at=datetime.now().isoformat(timespec="seconds"),
        )
        if self._repo.insert(_COLLECTION, row) is None:
            raise RuntimeError("交付物记录写入失败")
        logger.info(f"交付物已生成: id={did} template={template} size={len(pdf)}")
        return self._meta(row)

    # ── 读取 ──

    @staticmethod
    def _meta(r) -> dict:
        return {
            "id": r.id,
            "title": r.title,
            "name": f"{r.title}.pdf",
            "template": r.template,
            "size": r.size,
            "created_at": r.created_at,
            "url": f"/api/deliverables/{r.id}",
        }

    def list_by_session(self, session_id: str, user_id: int) -> list[dict]:
        """列出某会话的全部交付物（按时间正序）。"""
        rows = self._repo.find(_COLLECTION, {"session_id": session_id, "user_id": int(user_id)}, order_by="created_at")
        return [self._meta(r) for r in rows]

    def delete_by_session(self, user_id: int, session_id: str) -> int:
        """删除某会话的全部交付物（对象存储对象 + 记录），返回删除条数。

        会话删除时由组合根级联调用；避免残留 PDF（每份数 MB）。
        """
        where = {"session_id": session_id, "user_id": int(user_id)}
        rows = self._repo.find(_COLLECTION, where)
        if not rows:
            return 0
        keys = [r.object_key for r in rows if r.object_key]
        if self._os is not None and keys:
            try:
                self._os.delete_keys(keys)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"交付物对象删除失败: {e}")
        n = self._repo.delete_where(_COLLECTION, where)
        logger.info(f"会话交付物已清理: session={session_id} count={n}")
        return int(n or 0)

    def read(self, deliverable_id: str, *, user_id: int | None = None) -> tuple[bytes, str]:
        """取回交付物 PDF 字节与下载文件名。"""
        row = self._repo.get(_COLLECTION, deliverable_id)
        if row is None:
            raise NotFound("交付物不存在")
        if user_id is not None and int(row.user_id) != int(user_id):
            raise PermissionDenied("无权访问该交付物")
        data = self._os.get_bytes(row.object_key) if self._os is not None else None
        if data is None:
            raise NotFound("交付物文件不存在")
        return data, f"{row.title}.pdf"
