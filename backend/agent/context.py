"""SkillLoader: 从 prompts 目录加载 identity 与 skills，供 LLM 构建 system message。

支持的 skill 布局:
  1. 扁平: <prompts_dir>/skills/<skill>.md
  2. 嵌套: <prompts_dir>/skills/<skill>/SKILL.md (或 skill.md)

skill 文件格式 (YAML-like frontmatter + markdown body):
    ---
    name: skill_name
    description: 一句话描述
    include_identity: true|false
    inputs:
      - var1
      - var2
    ---
    Markdown body with {var1} and {var2} placeholders.

主要接口:
  - SkillLoader(prompts_dir) → 加载 identity 和 skills
  - skill_loader.identity: str — 系统身份文本
  - skill_loader.skills: dict — {名称: Skill} 映射
  - skill_loader.list_skills() → 概览字典
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from config._utils import _strip_quotes
from infra.logger import logger

# ── Skill ──


@dataclass
class Skill:
    """表示一个加载完成的 prompt skill。

    Attributes:
        name: skill 名称
        description: 一句话描述
        inputs: 模板变量名列表
        template: markdown 正文模板，支持 {variable} 占位符替换
        include_identity: 是否在组装消息时自动包含 identity system message
        source: skill 文件来源路径 (绝对路径)
        meta: frontmatter 中的原始元数据字典
    """
    name: str
    description: str
    inputs: list
    template: str
    include_identity: bool
    source: str = ""
    meta: dict = field(default_factory=dict)


# ── 工具函数 ──

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)


def _coerce_bool(s: str):
    """将字符串转换为 Python 的布尔值或数字类型。"""
    low = s.strip().lower()
    if low in ("true", "yes", "on"):
        return True
    if low in ("false", "no", "off"):
        return False
    try:
        if "." in low:
            return float(low)
        return int(low)
    except (ValueError, TypeError):
        pass
    return s


def parse_frontmatter(text: str) -> tuple:
    """解析带有 YAML 风格 frontmatter 的 markdown 文件。

    Returns:
        (meta, body) 二元组。
    """
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    raw_meta = m.group(1)
    body = m.group(2).strip("\n")
    return _parse_yaml_block(raw_meta), body


def _parse_yaml_block(text: str) -> dict:
    """手动解析 YAML 风格键值对块 (不使用 PyYAML)。"""
    result: dict = {}
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            i += 1
            continue
        if ":" not in line:
            i += 1
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()

        if value == "|":
            lines_joined = []
            i += 1
            if i < len(lines):
                indent = len(lines[i]) - len(lines[i].lstrip())
                while i < len(lines):
                    nxt = lines[i]
                    s = nxt.strip()
                    if s == "":
                        lines_joined.append("")
                        i += 1
                        continue
                    if len(nxt) - len(nxt.lstrip()) >= indent:
                        lines_joined.append(s)
                        i += 1
                    else:
                        break
            result[key] = " ".join(lines_joined)
        elif value:
            result[key] = _coerce_bool(_strip_quotes(value))
            i += 1
        else:
            items: list = []
            i += 1
            while i < len(lines):
                nxt = lines[i]
                if not nxt.strip():
                    i += 1
                    continue
                if nxt.lstrip().startswith("-"):
                    items.append(_strip_quotes(nxt.lstrip()[1:].strip()))
                    i += 1
                else:
                    break
            result[key] = items
    return result


# ── 工具函数 ──

def _load_identity(prompts_dir: Path) -> str:
    """从基线目录加载身份文件 (identity.md)。"""
    f = prompts_dir / "identity.md"
    if not f.exists():
        return ""
    return f.read_text(encoding="utf-8").strip()


class SkillLoader:
    """从 prompts 目录加载 identity 和 skills，供 LLM 构建 system message。

    Args:
        prompts_dir: prompts 目录路径（含 identity.md 和 skills/ 子目录）。
    """

    def __init__(self, prompts_dir: str | Path):
        skill_dir = Path(prompts_dir)
        if not skill_dir.is_dir():
            raise FileNotFoundError(f"prompts 目录不存在: {skill_dir}")

        self._skills: dict = {}
        self._load_skills_from(skill_dir)

        logger.debug(
            f"SkillLoader 就绪: skills={sorted(self._skills.keys())}"
        )

    def _load_skills_from(self, prompts_dir: Path):
        """从 prompts_dir 加载 skill 到 self._skills。"""
        for file, fallback in self._scan_skills(prompts_dir):
            self._register(self._load_one(file, fallback_name=fallback))

    def _scan_skills(self, root: Path):
        """递归扫描目录树，查找所有 skill 定义文件。"""
        for f in sorted(root.glob("*.md")):
            if f.name.lower() in ("skill.md", "readme.md"):
                continue
            yield f, f.stem
        for sub in sorted(root.iterdir()):
            if not sub.is_dir():
                continue
            skill_file = self._find_skill_file(sub)
            if skill_file is not None:
                yield skill_file, sub.name
            else:
                yield from self._scan_skills(sub)

    @staticmethod
    def _find_skill_file(directory: Path) -> Path | None:
        """在目录中查找 skill 定义文件。"""
        for name in ("SKILL.md", "skill.md"):
            f = directory / name
            if f.exists():
                return f
        return None

    def _load_one(self, file: Path, fallback_name: str) -> Skill | None:
        """从单个 .md 文件加载一个 skill。"""
        try:
            text = file.read_text(encoding="utf-8")
            meta, body = parse_frontmatter(text)
            name = meta.get("name") or fallback_name
            inputs = meta.get("inputs") or []
            if not isinstance(inputs, list):
                inputs = [inputs]
            return Skill(
                name=str(name),
                description=str(meta.get("description", "")),
                inputs=list(inputs),
                template=body,
                include_identity=bool(meta.get("include_identity", False)),
                source=str(file.resolve()),
                meta=meta,
            )
        except Exception as e:
            logger.error(f"加载 skill 失败 {file}: {e}")
            return None

    def _register(self, skill: Skill | None):
        """注册一个 skill 到技能字典中。"""
        if skill is None:
            return
        existing = self._skills.get(skill.name)
        if existing is not None:
            logger.warning(f"skill '{skill.name}' 被覆盖: {skill.source} 覆盖 {existing.source}")
        self._skills[skill.name] = skill

    def list_skills(self) -> dict:
        """返回当前已加载的所有 skill 的概览信息。"""
        return [
            {
                "value": name,
                "label": s.meta.get("label", name),
                "description": s.description,
            }
            for name, s in self._skills.items()
        ]

    def get_skill(self, name: str) -> Skill | None:
        """根据名称获取 skill。"""
        return self._skills.get(name)

# ── 工作流 ──

class WorkflowRouter:
    """工作流路由器，管理 prompts/workflow/ 目录下的工作流文件。"""

    def __init__(self, prompts_dir: str):
        self.workflow_dir: Path = Path(prompts_dir)
        self._workflows: dict[str, dict] = {}
        self._load_workflows_from()

    def _load_workflows_from(self, prompts_dir: str | None = None):
        root = Path(prompts_dir) if prompts_dir else self.workflow_dir
        for fpath in sorted(root.glob("*.md")):
            if fpath.name == "route.md":
                continue
            try:
                text = fpath.read_text(encoding="utf-8")
                meta, template = parse_frontmatter(text)
                wf_name = meta.get("name") or fpath.stem
                desc = meta.get("description") or ""
                self._workflows[wf_name] = {
                    "name": wf_name, "label": meta.get("label", wf_name),
                    "description": desc, "template": template,
                    "max_tool_iter": meta.get("max_tool_iter"),
                    "always_load": meta.get("always_load", False),
                }
            except Exception as e:
                logger.warning(f"工作流加载失败 {fpath.name}: {e}")
        logger.debug(f"WorkflowRouter 就绪: {len(self._workflows)} 个工作流")

    def get_workflow_content(self, name: str) -> str | None:
        wf = self._workflows.get(name)
        if wf is None:
            logger.warning(f"Workflow '{name}' 不存在")
            return None
        return wf["template"]

    def get_workflow_summaries(self) -> str:
        lines = ["Available workflows"]
        for n, info in self._workflows.items():
            d = info.get("description", "")
            lines.append(f"{n}: {d}" if d else n)
        return "\n".join(lines)

    def get_workflow_list(self) -> list[dict]:
        return [
            {
                "name": name,
                "label": info.get("label", name),
                "description": info.get("description", ""),
                "always_load": info.get("always_load", False),
            }
            for name, info in self._workflows.items()
        ]

class SystemContext:
    def __init__(self, prompts_dir: str):
        self.prompts_dir = Path(prompts_dir)
        self.identity = _load_identity(self.prompts_dir)
        self.style_router = SkillLoader(self.prompts_dir/"style")
        self.workflow_router =  WorkflowRouter(self.prompts_dir/"workflow")
