# Paper Helper · 博士论文个人 Wiki

一个用于博士论文研究的个人知识库，基于 **Andrej Karpathy 的「LLM Wiki」范式**。
核心理念：**知识编译优于检索**——把文献一次性编译成相互链接的 Markdown 页面网络，
由 AI Agent 负责簿记维护，人只负责策展。无需向量数据库 / RAG。

## 设计：三层架构 + 三个核心操作

```
原始资料层 (raw/, 只读)  →  Wiki 层 (wiki/, Agent 编译)  →  规则层 (purpose/schema/AGENTS)
```

- **Ingest（摄入）**：把 `raw/sources/` 的文献编译成结构化 Wiki 页面，自动建立交叉引用。
- **Query（查询）**：基于已编译的知识网络回答问题，沉淀新洞察。
- **Lint（巡检）**：检查孤立页面、死链、知识空白，保持库的健康。

## 目录结构

```
paper-helper/
├── purpose.md              # 论文目标、研究问题、范围（你维护）
├── schema.md               # Wiki 结构规则、页面类型、frontmatter（你维护）
├── AGENTS.md               # Agent 工作规范：三个核心操作（你维护）
├── raw/
│   ├── sources/            # 原始文献/资料（只读、不可变）—— 你把 PDF/笔记放这里
│   └── assets/             # 本地图片
└── wiki/                   # 由 Agent 编译维护
    ├── index.md            # 内容目录 / 导航
    ├── log.md              # 操作审计日志（追加式）
    ├── overview.md         # 全局概要（自动更新）
    ├── sources/            # 单篇文献的结构化摘要
    ├── concepts/           # 理论、方法、技术、术语
    ├── entities/           # 人物、机构、数据集、工具、会议/期刊
    ├── research-questions/ # 研究问题展开
    ├── experiments/        # 实验设计与运行记录
    ├── synthesis/          # 跨文献综合（综述素材）
    ├── comparisons/        # 方法/模型并列对比
    └── queries/            # 沉淀的问答
```

每个 `wiki/` 子目录下的 `_template.md` 是该类页面的格式模板。

## 怎么用（在 Cursor / Claude Code 中）

1. 先填写 `purpose.md`——写下你的研究方向、核心研究问题和论文大纲。
2. 把文献 PDF 或读书笔记放进 `raw/sources/`。
3. 对 Agent 说：**“摄入 raw/sources 里的新资料”**（Ingest）。
4. 之后随时提问：**“关于 X，我库里的文献怎么说？”**（Query）。
5. 定期说：**“巡检一下知识库”**（Lint）。

## 🚀 给非技术用户：一键启动（推荐）

**macOS：双击根目录的 `start.command`** 即可。首次启动会自动安装依赖并打开浏览器，
之后所有操作都在网页里点按钮完成，无需命令行：

| 工具栏按钮 | 作用 |
|-----------|------|
| ＋ 添加文献 | 选择/拖入 PDF，自动存入 `raw/sources/` |
| ✨ 分析 | 调用大模型把待处理文献摄入成 wiki 页面 + 概念/关联（需先在「设置」填 API Key） |
| ↻ 刷新 | 重新扫描知识库，更新论文库与图谱 |
| ⚙ 设置 | 填写大模型 API（OpenAI 兼容：OpenAI / DeepSeek / 通义 / Moonshot 等） |

> 首次使用请先点「设置」填入 API 地址、Key、模型名（如 `gpt-4o-mini`）。Key 只存在本机
> `.paper-helper/config.json`，不会上传，也不会进入 Git。未填 Key 时点「分析」会提示——
> 此时也可改在 Cursor 里让 AI 执行摄入。

三个视图：**论文库**（文献卡片，可打开 PDF / 删除）、**知识图谱**（`[[wikilink]]` 力导向图，
可缩放/拖拽/点击）、**全部页面**（按类型分组）。

## 可视化界面（静态离线版）

不启动服务也可生成一个纯静态、可离线 `file://` 打开的只读页面（无添加/分析按钮）：

```bash
python3 tools/build_site.py   # 生成 wiki-viewer.html，双击打开
```

> `tools/wiki_core.py` 是扫描与渲染的公共核心，`build_site.py`（静态）与 `app.py`（服务）共用。

## 致谢

方法论来自 [Karpathy 的 llm-wiki.md](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)，
结构参考 [nashsu/llm_wiki](https://github.com/nashsu/llm_wiki)。本仓库是面向博士论文场景的纯 Markdown 实现，
可直接作为 Obsidian 仓库打开。
