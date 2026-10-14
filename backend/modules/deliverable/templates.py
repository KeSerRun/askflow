"""modules.deliverable.templates —— 内置交付物模板（3 套）+ 预览样例内容。

每个模板是一个 dict：
- ``name`` 模板标识（工具 `create_deliverable` 的 template 参数）；
- ``label`` / ``description`` 展示名与用途（供模型选择）；
- ``fields`` 内容字段说明（供模型按结构填写 content）；
- ``accent`` 主题色（``#rrggbb``；渲染器据此生成强调条 / 表头底色等）；
- ``css`` 模板自定义样式（追加在默认样式之后，可覆盖）；
- ``html`` Jinja2 模板（``{{ title }}`` / ``{{ today }}`` / ``{{ content.* }}``；文本字段用 ``| md``）；
- ``version`` 内置版本（启动时据此安全升级未被人工编辑的模板）。

约定：段落类字段用 ``{{ content.x | md }}``（Markdown→HTML：标题 / 列表 / 加粗 / 表格）；
表格单元格内保持纯文本（``{{ }}``），避免块级元素嵌套在 ``<td>`` 里。
"""

from __future__ import annotations

# ── 研究报告 ──
RESEARCH_REPORT = {
    "name": "research_report",
    "version": 3,
    "label": "研究报告",
    "description": "结构化的研究报告：摘要 / 背景 / 方法 / 主要发现 / 结论 / 参考来源。适合调研后成文。",
    "accent": "#d4734e",
    "css": "",
    "fields": [
        {"key": "summary", "label": "摘要", "type": "text(markdown)"},
        {"key": "background", "label": "研究背景", "type": "text(markdown)"},
        {"key": "method", "label": "研究方法", "type": "text(markdown)"},
        {"key": "findings", "label": "主要发现", "type": "list[{title, detail(markdown)}]"},
        {"key": "conclusion", "label": "结论", "type": "text(markdown)"},
        {"key": "references", "label": "参考来源", "type": "list[str]"},
    ],
    "html": """<div class="hero">
  <div class="kicker">研究报告 · {{ today }}</div>
  <h1>{{ title }}</h1>
</div>
{% if content.summary %}<h2>摘要</h2>{{ content.summary | md }}{% endif %}
{% if content.background %}<h2>研究背景</h2>{{ content.background | md }}{% endif %}
{% if content.method %}<h2>研究方法</h2>{{ content.method | md }}{% endif %}
{% if content.findings %}
<h2>主要发现</h2>
{% for f in content.findings %}
  {% if f.title %}<h3>{{ f.title }}</h3>{% endif %}
  {% if f.detail %}{{ f.detail | md }}{% endif %}
{% endfor %}
{% endif %}
{% if content.conclusion %}<h2>结论</h2>{{ content.conclusion | md }}{% endif %}
{% if content.references %}
<h2>参考来源</h2>
<ul>{% for r in content.references %}<li>{{ r | md }}</li>{% endfor %}</ul>
{% endif %}""",
}

# ── 规划报告 ──
PLANNING_REPORT = {
    "name": "planning_report",
    "version": 3,
    "label": "规划报告",
    "description": "规划/实施方案：目标 / 背景 / 实施阶段（任务·负责人·时间）/ 里程碑 / 风险与应对 / 资源需求。",
    "accent": "#3f6ea8",
    "css": "",
    "fields": [
        {"key": "goal", "label": "目标", "type": "text(markdown)"},
        {"key": "background", "label": "背景", "type": "text(markdown)"},
        {"key": "phases", "label": "实施阶段", "type": "list[{name, tasks:[str], owner, timeline}]"},
        {"key": "milestones", "label": "里程碑", "type": "list[{name, date}]"},
        {"key": "risks", "label": "风险与应对", "type": "list[{risk, mitigation}]"},
        {"key": "resources", "label": "资源需求", "type": "text(markdown)"},
    ],
    "html": """<div class="hero">
  <div class="kicker">规划报告 · {{ today }}</div>
  <h1>{{ title }}</h1>
</div>
{% if content.goal %}<h2>目标</h2>{{ content.goal | md }}{% endif %}
{% if content.background %}<h2>背景</h2>{{ content.background | md }}{% endif %}
{% if content.phases %}
<h2>实施阶段</h2>
<table>
  <tr><th>阶段</th><th>任务</th><th>负责人</th><th>时间</th></tr>
  {% for p in content.phases %}
  <tr>
    <td>{{ p.name }}</td>
    <td>{% for t in (p.tasks or []) %}{{ t }}{% if not loop.last %}<br/>{% endif %}{% endfor %}</td>
    <td>{{ p.owner }}</td>
    <td>{{ p.timeline }}</td>
  </tr>
  {% endfor %}
</table>
{% endif %}
{% if content.milestones %}
<h2>里程碑</h2>
<table>
  <tr><th>里程碑</th><th>时间</th></tr>
  {% for m in content.milestones %}<tr><td>{{ m.name }}</td><td>{{ m.date }}</td></tr>{% endfor %}
</table>
{% endif %}
{% if content.risks %}
<h2>风险与应对</h2>
<table>
  <tr><th>风险</th><th>应对措施</th></tr>
  {% for r in content.risks %}<tr><td>{{ r.risk }}</td><td>{{ r.mitigation }}</td></tr>{% endfor %}
</table>
{% endif %}
{% if content.resources %}<h2>资源需求</h2>{{ content.resources | md }}{% endif %}""",
}

# ── 调查报告 ──
SURVEY_REPORT = {
    "name": "survey_report",
    "version": 3,
    "label": "调查报告",
    "description": "调查报告：调查目的 / 方法 / 样本 / 调查结果（含数据表）/ 结论 / 建议。",
    "accent": "#3f8f6f",
    "css": "",
    "fields": [
        {"key": "objective", "label": "调查目的", "type": "text(markdown)"},
        {"key": "method", "label": "调查方法", "type": "text(markdown)"},
        {"key": "sample", "label": "样本情况", "type": "text(markdown)"},
        {"key": "findings", "label": "调查结果", "type": "list[{title, detail(markdown), data:{指标:值}}]"},
        {"key": "conclusion", "label": "结论", "type": "text(markdown)"},
        {"key": "recommendations", "label": "建议", "type": "list[str]"},
    ],
    "html": """<div class="hero">
  <div class="kicker">调查报告 · {{ today }}</div>
  <h1>{{ title }}</h1>
</div>
{% if content.objective %}<h2>调查目的</h2>{{ content.objective | md }}{% endif %}
{% if content.method %}<h2>调查方法</h2>{{ content.method | md }}{% endif %}
{% if content.sample %}<h2>样本情况</h2>{{ content.sample | md }}{% endif %}
{% if content.findings %}
<h2>调查结果</h2>
{% for f in content.findings %}
  {% if f.title %}<h3>{{ f.title }}</h3>{% endif %}
  {% if f.detail %}{{ f.detail | md }}{% endif %}
  {% if f.data %}
  <table>
    <tr><th>指标</th><th>数值</th></tr>
    {% for k, v in (f.data or {}).items() %}<tr><td>{{ k }}</td><td>{{ v }}</td></tr>{% endfor %}
  </table>
  {% endif %}
{% endfor %}
{% endif %}
{% if content.conclusion %}<h2>结论</h2>{{ content.conclusion | md }}{% endif %}
{% if content.recommendations %}
<h2>建议</h2>
<ul>{% for r in content.recommendations %}<li>{{ r | md }}</li>{% endfor %}</ul>
{% endif %}""",
}

BUILTIN_TEMPLATES = [RESEARCH_REPORT, PLANNING_REPORT, SURVEY_REPORT]

# 预览样例内容（管理端「预览 PDF」用；含 Markdown 以演示渲染效果）
SAMPLE_CONTENT = {
    "research_report": {
        "summary": "本报告围绕**示例主题**，梳理背景、方法与主要发现。\n\n- 范围：近一年公开资料\n- 结论：可落地",
        "background": "示例背景：说明研究缘起、范围与关注的核心问题。",
        "method": "示例方法：\n\n1. 检索公开资料\n2. 交叉验证关键信息",
        "findings": [
            {"title": "发现一", "detail": "第一条主要发现的**示例描述**，用于查看段落排版。"},
            {"title": "发现二", "detail": "第二条主要发现的示例描述。"},
        ],
        "conclusion": "示例结论：给出可执行的判断与后续研究方向。",
        "references": ["示例来源 A", "示例来源 B"],
    },
    "planning_report": {
        "goal": "示例目标：在既定周期内完成示例事项并达成预期效果。",
        "background": "示例背景：说明规划的必要性与约束条件。",
        "phases": [
            {
                "name": "阶段一 调研",
                "tasks": ["梳理现状", "确定指标"],
                "owner": "张三",
                "timeline": "第 1-2 周",
            },
            {
                "name": "阶段二 实施",
                "tasks": ["落地改造", "灰度验证"],
                "owner": "李四",
                "timeline": "第 3-6 周",
            },
        ],
        "milestones": [
            {"name": "方案评审通过", "date": "第 2 周末"},
            {"name": "上线验收", "date": "第 6 周末"},
        ],
        "risks": [
            {"risk": "进度延期", "mitigation": "设置缓冲并每周对齐"},
            {"risk": "资源不足", "mitigation": "提前协调人力"},
        ],
        "resources": "示例资源：\n\n- 人力 3 人\n- 预算若干",
    },
    "survey_report": {
        "objective": "示例目的：了解目标人群对示例事项的**认知与偏好**。",
        "method": "示例方法：线上问卷 + 抽样访谈。",
        "sample": "示例样本：有效样本 500 份，覆盖 3 个城市。",
        "findings": [
            {
                "title": "结果一",
                "detail": "多数受访者倾向方案 A。",
                "data": {"方案 A": "62%", "方案 B": "28%", "其他": "10%"},
            },
            {
                "title": "结果二",
                "detail": "价格是主要决策因素。",
                "data": {"价格": "45%", "品牌": "30%", "口碑": "25%"},
            },
        ],
        "conclusion": "示例结论：方案 A 更受青睐，建议优先推进。",
        "recommendations": ["优先落地方案 A", "结合价格策略做分层"],
    },
}
