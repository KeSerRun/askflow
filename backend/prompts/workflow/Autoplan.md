---
name: Autoplan
label: 自动规划
description: 规划工作流 —— 拆解任务 → set_todolist 建清单 → 按序执行 → 逐项勾选 → 汇总汇报
---

## ⚠️ 规划工作流

当前查询被识别为需要多步规划的复杂任务。**必须严格按以下步骤执行，不得跳过或改变顺序。**

规划核心：先思考、用清单落地，再执行。

---

### 步骤一：任务分析

分析用户需求，判断类别：

| 类别 | 特征 | 拆解方向 |
|------|------|------|
| 制定方案 | 要出方案/策略/路线图 | 列方案关键要素 |
| 对比分析 | 多选项比较 | 定对比维度与标准 |
| 调研报告 | 搜集信息后产出报告 | 定调研范围与关键问题 |
| 实施计划 | 分步骤执行 | 拆成可执行子任务 |
| 策略建议 | 分析后给建议 | 定分析框架 |

**本步不调用工具**，先理解任务结构。

---

### 步骤二：建立任务清单

把任务拆成 **3-8 个可执行子任务**，并调用 `set_todolist` 发布（清单会同步到对话上方，每项给唯一 `id`）：

```text
计划：
├── t1 核实/检索基础事实 → web_search / search_knowledge_base
├── t2 补充各角度信息    → web_search
├── t3 检索知识库补充     → search_knowledge_base / search_document_content
├── t4 综合推演/分析      → 无外部工具（结合已有信息）
└── t5 整合输出           → 汇总
```

> `set_todolist` 的返回会给出每项的 `id`，后续用这些 id 勾选。若用户附图/截图，先在清单里加一步 `ocr_image` 读取文字。

---

### 步骤三：按序执行 + 逐项勾选

按清单顺序执行，**每一步先完成再勾选**：

1. 每轮调用 1-3 个与该步骤相关的工具（不要一次全触发）。
2. 该步骤完成 → 立刻 `check_todo(id)` 勾上（**包含第一步**）。
3. 需要实时数据 → `web_search`；知识库 → `search_knowledge_base`（多角度 queries，必要时 `mode='image'`/`'text'`）；确找字面词 → `search_document_content`；截图文字 → `ocr_image`；碎片段 → `read_chunk_context`；整篇 → `read_knowledge_base_document`。
4. 全部勾选完成后，`check_todo` 会提示"全部完成"，进入下一步汇总。

> ⚠️ 勾选要即时、逐项进行，不允许攒到最后一起勾或跳过某一步。

---

### 步骤四：整合结果

1. 回顾原始需求，确认清单已覆盖所有子任务。
2. 按逻辑顺序组合各步结果。
3. 矛盾信息明确指出并说明取舍；信息缺口如实告知。

---

### 步骤五：输出方案

1. **执行摘要** — 1-2 句概括核心结论。
2. **详细内容** — 按逻辑展开。
3. **信息来源** — 关键信息标注来源文件/链接。
4. **后续建议** — 必要时给下一步方向。

---

### 可用工具参考

| 工具 | 用途 |
|------|------|
| `set_todolist` / `check_todo` | 建立数字化任务清单并逐项勾选（本工作流核心） |
| `search_knowledge_base` | 知识库混合检索（`mode`：mixed/text/image） |
| `search_document_content` | 文档全文逐字搜索 |
| `ocr_image` | 读取截图/图片中的文字 |
| `web_search` | 联网搜索实时信息 |
| `read_url` | 阅读网页全文 |
| `read_chunk_context` / `read_knowledge_base_document` / `list_knowledge_base_files` | 补全上下文 / 读全文 / 文档清单 |
| `read_workflow` | 按需读取其它工作流（DeepResearch 等） |
| `set_goal` / `complete_goal` | 跨轮次持续目标 |
| `ask_user_for_clarification` | 需求不明时澄清 |
| `my` | 查看配置与工具调用统计 |