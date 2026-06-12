# Paper Helper · 博士论文个人 Wiki

一个用于博士论文研究的个人知识库，基于 **Andrej Karpathy 的「LLM Wiki」范式**。
核心理念：**知识编译优于检索**——把文献一次性编译成相互链接的 Markdown 页面网络，
由 AI Agent 负责簿记维护，人只负责策展。无需向量数据库 / RAG。

## 设计：三层架构 + 三个核心操作

```
原始资料层 (raw/, 只读)  →  Wiki 层 (wiki/, Agent 编译)  →  规则层 (purpose/schema/AGENTS)
```

- **Ingest（摄入）**：应用内「分析」或 Cursor Agent 把文献编译成 Wiki 页面。
- **Query（查询）**：应用内「查询」或 Cursor Agent 基于 wiki 作答。
- **Lint（巡检）**：应用内「巡检」或 Cursor Agent 检查死链、孤立页等。

## 目录结构

```
paper-helper/
├── topics/<id>/          # 多选题数据（wiki、raw、规则）
├── templates/            # 规则与 wiki 模板
├── .paper-helper/        # 配置、当前选题（本地，不入 Git）
├── tools/                # 桌面应用与服务
├── Paper-Helper.app      # macOS 双击启动（桌面窗口）
└── start.command         # 转发到 .app
```

## 怎么用（推荐：桌面应用）

| 系统 | 启动方式 |
|------|----------|
| macOS | 双击 `Paper-Helper.app` 或 `start.command` |
| Windows | 双击 `Paper-Helper.vbs` 或 `start.bat` |
| 命令行 | `python tools/entry.py`（桌面）/ `python tools/launch.py`（浏览器） |

启动后所有操作在窗口内完成：

| 按钮 | 作用 |
|------|------|
| ＋ 添加文献 | 选择或**拖放** PDF/Word/Markdown 到论文库 |
| ✨ 分析 | LLM 摄入待处理文献（可取消） |
| 💬 查询 | 基于 wiki 问答，沉淀到 `wiki/queries/` |
| 🩺 巡检 | 孤立页、死链、知识空白 |
| ↻ 刷新 | 重扫知识库，更新 index + overview |
| 📤 BibTeX | 导出文献 BibTeX |
| 💾 备份 | 当前选题快照到 `topics/.snapshots/` |
| ⚙ 设置 | 大模型 API（OpenAI 兼容） |

**四视图**：论文库、知识图谱、全部页面、**文档编辑**（docx 批注 + Todo + 修订留痕）。

### 文档编辑（WPS + Git 范式）

- 导入 `.docx`，在线编辑并处理批注
- **抓取批注** → 自动生成 Todo 列表，点击跳转正文位置
- 在窗口内修改段落、勾选完成批注
- **存档** 生成修订记录（类似 git log），可查看历史进度

**多选题**：顶栏切换/新建/重置选题，编辑研究规则（purpose/schema/AGENTS）。

> Key 仅存本机 `.paper-helper/config.json`。也可在 Cursor 中按 `AGENTS.md` 执行摄入/查询/巡检。

## 可视化界面（静态离线版）

```bash
python3 tools/build_site.py   # 生成 wiki-viewer.html
```

## 打包分发（微信传给别人）

```bash
python3 build.py           # 独立版 + 源码版（推荐）
python3 build.py --source  # 仅源码版（体积小，适合微信）
```

产物在 `release/`：

| 文件 | 说明 |
|------|------|
| `Paper-Helper-mac-*.zip` / `.dmg` | macOS 独立版，**无需 Python** |
| `Paper-Helper-mac-source.zip` | macOS 源码版，首次启动自动装依赖 |
| `Paper-Helper-win-*.zip` | Windows 独立版（需在 Windows 上打包） |
| `Paper-Helper-win-source.zip` | Windows 源码版 |

对方解压后阅读 `安装说明.txt` 即可。独立版约 200–400 MB；源码版约 5–15 MB。

## 致谢

方法论来自 [Karpathy llm-wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)。
本仓库面向博士论文场景，可作为 Obsidian 仓库使用。
