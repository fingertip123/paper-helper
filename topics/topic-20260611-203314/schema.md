---
type: schema
title: Wiki 结构规则
updated: 2026-06-10
---

# Schema · Wiki 如何运作

> 这是知识库的“规矩”。Agent 按本文件定义的格式与禁忌编译 Wiki 页面。
> 区别于 [[purpose]]（方向意图）——本文件只管**结构**。

## 1. 三层架构

| 层 | 目录 | 谁写 | 是否可变 |
|----|------|------|----------|
| 原始资料层 | `raw/` | 人类放入 | **只读、不可变**（Agent 不得修改） |
| Wiki 层 | `wiki/` | Agent 编译 | 可反复重写 |
| 规则层 | `purpose.md` / `schema.md` / `AGENTS.md` | 人类 | 由人维护 |

## 2. 页面类型（page types）

| 目录 | 类型 | 内容 |
|------|------|------|
| `wiki/sources/` | source | 单篇文献/资料的结构化摘要（一篇一页） |
| `wiki/concepts/` | concept | 理论、方法、模型、技术、术语 |
| `wiki/entities/` | entity | 人物、机构、数据集、工具、会议/期刊 |
| `wiki/research-questions/` | rq | 研究问题的展开、现状与进展 |
| `wiki/experiments/` | experiment | 实验设计、假设、运行记录、结果 |
| `wiki/synthesis/` | synthesis | 跨多篇文献的综合分析、综述片段 |
| `wiki/comparisons/` | comparison | 方法/模型/数据集的并列对比 |
| `wiki/queries/` | query | 沉淀下来的有价值问答 |

## 3. Frontmatter 规范

每个 Wiki 页面顶部必须有 YAML frontmatter：

```yaml
---
type: concept            # 上表中的页面类型
title: 页面标题
aliases: [别名1, 别名2]   # 可选，便于 [[wikilink]] 匹配
sources: [paper-key-1]   # 本页知识来源的 source key（可追溯到 raw/）
tags: [方法, 深度学习]
created: 2026-06-10
updated: 2026-06-10
---
```

- `sources[]` 是来源可追溯的关键：删除某篇文献时，按它级联清理。
- 文件名用 `kebab-case` 英文或稳定中文短语，避免空格。

## 4. 交叉引用规范

- 一律使用 `[[wikilink]]` 链接其他页面：`[[transformer]]`、`[[smith-2023]]`。
- 别名链接：`[[transformer|自注意力机制]]`。
- 摄入新资料时，**一次性更新所有相关页面的交叉引用**（这是 Agent 的核心职责）。

## 5. 文献引用 key 约定

- 格式：`第一作者姓-年份`，重名加字母，如 `smith-2023`、`smith-2023b`。
- `raw/sources/` 里的原始文件与 `wiki/sources/<key>.md` 摘要页一一对应。

## 6. 禁忌（不要做）

- 不修改 `raw/` 下的任何文件。
- 不创建孤立页面（每个新页面至少链接一个已有页面，并被 [[index]] 收录）。
- 不臆造文献内容；无法确定的标注为待核实并写入审核区。
- 不使用向量数据库 / RAG —— Markdown + wikilink + 上下文窗口已足够。
