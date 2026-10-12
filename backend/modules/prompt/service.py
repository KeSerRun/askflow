"""modules.prompt.service —— Prompt（系统提示词）管理用例。

管理 ``backend/prompts`` 目录下的三类提示词：
- **identity**：``prompts/identity/{Name}.md``（目录，多个身份预置，可切换当前身份）；
- **workflow**：``prompts/workflow/{Name}.md``（frontmatter + 正文）；
- **style**：``prompts/style/{name}/SKILL.md``（frontmatter + 正文）。

保存 / 删除 / 切换身份后通过组合根注入的 ``reloader`` 触发 ``SystemContext`` 热重载，
改动对后续对话立即生效（无需重启）。
"""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import Optional

from agent.context import parse_frontmatter
from core.app_errors import InvalidInput, NotFound

_NAME_RE = re.compile(r"^[\w][\w._-]*$")

_STYLE_FILE_NAMES = ("SKILL.md", "skill.md")


class PromptService:
    """Prompt 文件增删改查 + 热重载。"""

    def __init__(self, prompts_dir: str, reloader: Optional[callable] = None):
        """初始化。

        Args:
            prompts_dir: ``backend/prompts`` 目录。
            reloader: 可选回调，保存/删除后触发 SystemContext 重载。
        """
        self.root = Path(prompts_dir)
        self.identity_file = self.root / "identity.md"   # 旧版单文件（迁移用）
        self.identity_dir = self.root / "identity"
        self.workflow_dir = self.root / "workflow"
        self.style_dir = self.root / "style"
        self._reloader = reloader
        # 存量嵌套 style/{name}/SKILL.md → 扁平 style/{name}.md（幂等）
        self._migrate_flat_styles()
        # 旧版 identity.md → identity/ 目录（幂等），并确保存在活动身份
        self._migrate_identity()

    # ── 内部 ──

    def _reload(self) -> None:
        if callable(self._reloader):
            try:
                self._reloader()
            except Exception:  # noqa: BLE001
                pass

    def _migrate_flat_styles(self) -> None:
        """把旧嵌套 ``style/{name}/SKILL.md`` 迁移为扁平 ``style/{name}.md``（幂等）。

        迁移后在 style 目录只保留扁平 ``*.md``，删除空目录；
        有改动则触发一次热重载（让运行中的 SystemContext 从扁平文件重建）。
        """
        if not self.style_dir.is_dir():
            return
        import shutil

        moved = False
        for sub in list(self.style_dir.iterdir()):
            if not sub.is_dir():
                continue
            f = next((sub / n for n in _STYLE_FILE_NAMES if (sub / n).is_file()), None)
            if f is None:
                continue
            dest = self.style_dir / f"{sub.name}.md"
            if not dest.exists():
                try:
                    shutil.copy2(f, dest)
                    moved = True
                except OSError:
                    continue
            try:
                shutil.rmtree(sub)
            except OSError:
                pass
        if moved:
            self._reload()

    def _migrate_identity(self) -> None:
        """旧版 ``identity.md`` → ``identity/`` 目录（幂等），并确保存在活动身份标记。"""
        try:
            self.identity_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            return
        if self.identity_file.is_file() and not (self.identity_dir / "identity.md").exists():
            try:
                shutil.copy2(self.identity_file, self.identity_dir / "identity.md")
            except OSError:
                pass
        active = self.identity_dir / ".active"
        if not active.exists():
            files = sorted(self.identity_dir.glob("*.md"))
            if files:
                try:
                    active.write_text(files[0].stem, encoding="utf-8")
                except OSError:
                    pass

    @staticmethod
    def _name(name: str, label: str = "名称") -> str:
        """规范化名称（防路径穿越，限制字符集）。"""
        name = os.path.basename((name or "").strip())
        if not _NAME_RE.match(name):
            raise InvalidInput(f"{label}非法（仅允许字母/数字/._-，不含路径）: {name!r}")
        return name

    @staticmethod
    def _read_md(path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8")
        except FileNotFoundError:
            raise NotFound(f"文件不存在: {path}")
        except OSError as e:
            raise InvalidInput(f"读取失败: {e}")

    def _write_md(self, path: Path, content: str) -> None:
        if not content or not content.strip():
            raise InvalidInput("内容不能为空")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    @staticmethod
    def _meta(path: Path) -> dict:
        """读取文件 frontmatter 元信息（name/label/description 等）。"""
        try:
            meta, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return {}
        return {k: meta.get(k) for k in ("name", "label", "description") if meta.get(k) is not None}

    # ── 概览 ──

    def overview(self) -> dict:
        """列出三类提示词的名称与元信息（不含正文）。"""
        identities: list[dict] = []
        if self.identity_dir.is_dir():
            for f in sorted(self.identity_dir.glob("*.md")):
                meta = self._meta(f)
                identities.append({
                    "name": meta.get("name") or f.stem,
                    "label": meta.get("label") or meta.get("name") or f.stem,
                    "description": meta.get("description") or "",
                    "path": str(f),
                })

        workflows: list[dict] = []
        if self.workflow_dir.is_dir():
            for f in sorted(self.workflow_dir.glob("*.md")):
                if f.name == "route.md":
                    continue
                meta = self._meta(f)
                workflows.append({
                    "name": meta.get("name") or f.stem,
                    "label": meta.get("label") or meta.get("name") or f.stem,
                    "description": meta.get("description") or "",
                    "path": str(f),
                })

        styles: list[dict] = []
        if self.style_dir.is_dir():
            for f in sorted(self.style_dir.glob("*.md")):
                if f.name.lower() in ("skill.md", "readme.md"):
                    continue
                meta = self._meta(f)
                styles.append({
                    "name": meta.get("name") or f.stem,
                    "label": meta.get("label") or meta.get("name") or f.stem,
                    "description": meta.get("description") or "",
                    "path": str(f),
                })

        return {
            "identities": identities,
            "identity_active": self.active_identity(),
            "workflows": workflows,
            "styles": styles,
        }

    # ── identity（目录多预置，可切换当前身份） ──

    def identity_list(self) -> dict:
        """身份列表 + 当前活动身份。"""
        return {"active": self.active_identity(), "items": self.overview()["identities"]}

    def active_identity(self) -> str:
        """当前选中的身份名（``identity/{name}.md`` 的文件名；无则空串）。"""
        active = self.identity_dir / ".active"
        if active.is_file():
            name = active.read_text(encoding="utf-8").strip()
            if (self.identity_dir / f"{name}.md").is_file():
                return name
        files = sorted(self.identity_dir.glob("*.md"))
        return files[0].stem if files else ""

    def get_identity(self, name: str = "") -> dict:
        """读取指定身份文件内容；``name`` 为空时取当前活动身份。"""
        if not name:
            name = self.active_identity()
        if not name:
            raise NotFound("identity 目录下没有身份文件")
        path = self.identity_dir / f"{self._name(name, '身份名')}.md"
        content = self._read_md(path)
        meta = self._meta(path)
        return {
            "name": meta.get("name") or path.stem,
            "active": path.stem == self.active_identity(),
            "content": content,
            "path": str(path),
        }

    def save_identity(self, name: str, content: str) -> dict:
        name = self._name(name, "身份名")
        path = self.identity_dir / f"{name}.md"
        self._write_md(path, content)
        if not (self.identity_dir / ".active").exists():
            (self.identity_dir / ".active").write_text(name, encoding="utf-8")
        self._reload()
        return {"message": f"identity「{name}」已保存", "path": str(path)}

    def delete_identity(self, name: str) -> dict:
        name = self._name(name, "身份名")
        path = self.identity_dir / f"{name}.md"
        if not path.is_file():
            raise NotFound(f"不存在: {name}")
        path.unlink()
        if name == self.active_identity():
            active = self.identity_dir / ".active"
            if active.exists():
                active.unlink(missing_ok=True)
            files = sorted(self.identity_dir.glob("*.md"))
            if files:
                self.set_active_identity(files[0].stem)
        self._reload()
        return {"message": f"identity「{name}」已删除"}

    def set_active_identity(self, name: str) -> dict:
        name = self._name(name, "身份名")
        if not (self.identity_dir / f"{name}.md").is_file():
            raise NotFound(f"身份不存在: {name}")
        (self.identity_dir / ".active").write_text(name, encoding="utf-8")
        self._reload()
        return {"message": f"当前 identity 已切换为「{name}」", "active": name}

    # ── workflow / style 通用 ──

    def _dir_for(self, category: str) -> Path:
        return {
            "workflow": self.workflow_dir,
            "style": self.style_dir,
            "identity": self.identity_dir,
        }.get(category) or self.style_dir

    def _item_path(self, category: str, name: str) -> Path:
        name = self._name(name, label="名称")
        return self._dir_for(category) / f"{name}.md"

    def list_category(self, category: str) -> list[dict]:
        data = self.overview()
        if category == "workflow":
            return data.get("workflows", [])
        if category == "style":
            return data.get("styles", [])
        return data.get("identities", [])

    def get_item(self, category: str, name: str) -> dict:
        path = self._item_path(category, name)
        content = self._read_md(path)
        meta = self._meta(path)
        display = meta.get("name") or (
            path.stem if category in ("workflow", "identity") else path.parent.name
        )
        return {
            "category": category,
            "name": display,
            "path": str(path),
            "content": content,
        }

    def save_item(self, category: str, name: str, content: str) -> dict:
        path = self._item_path(category, name)
        self._write_md(path, content)
        self._reload()
        return {"message": "已保存", "category": category, "name": name, "path": str(path)}

    def delete_item(self, category: str, name: str) -> dict:
        path = self._item_path(category, name)
        if path.is_file():
            path.unlink()
        else:
            raise NotFound(f"不存在: {name}")
        self._reload()
        return {"message": "已删除", "category": category, "name": name}