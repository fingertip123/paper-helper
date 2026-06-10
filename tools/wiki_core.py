#!/usr/bin/env python3
"""Wiki 公共核心：扫描 wiki/raw、构造可视化数据、生成 index、渲染 HTML 页面。

被 build_site.py（生成静态页）与 app.py（本地服务）共同复用，避免逻辑重复。
"""

import os
import re
import json
from datetime import datetime

rootdir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
wikidir = os.path.join(rootdir, "wiki")
rawsourcesdir = os.path.join(rootdir, "raw", "sources")
outputpath = os.path.join(rootdir, "wiki-viewer.html")

# 各页面类型的展示配置：标签 + 颜色 + 目录
typeconfig = {
    "source": {"label": "文献", "color": "#4f9dde", "dir": "sources"},
    "concept": {"label": "概念", "color": "#e0a34f", "dir": "concepts"},
    "entity": {"label": "实体", "color": "#9b6fde", "dir": "entities"},
    "rq": {"label": "研究问题", "color": "#de5f7a", "dir": "research-questions"},
    "experiment": {"label": "实验", "color": "#4fcf9d", "dir": "experiments"},
    "synthesis": {"label": "综合", "color": "#5fc7de", "dir": "synthesis"},
    "comparison": {"label": "对比", "color": "#cf8f4f", "dir": "comparisons"},
    "query": {"label": "问答", "color": "#9fae5f", "dir": "queries"},
    "purpose": {"label": "目标", "color": "#de7f4f", "dir": ""},
    "unknown": {"label": "其他", "color": "#888888", "dir": ""},
}

wikilinkpattern = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")
frontmatterpattern = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def ParseFrontmatter(ntext):
    """从 Markdown 文本中提取 YAML frontmatter（仅支持本项目用到的简单标量/列表）。"""
    omatch = frontmatterpattern.match(ntext)
    oresult = {}
    if not omatch:
        return oresult, ntext
    for line in omatch.group(1).split("\n"):
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            oresult[key] = [x.strip() for x in inner.split(",") if x.strip()] if inner else []
        else:
            oresult[key] = value
    return oresult, ntext[omatch.end():]


def ExtractLinks(nbody):
    """提取正文中的 [[wikilink]] 目标（去重）。"""
    vtargets = []
    for m in wikilinkpattern.finditer(nbody):
        target = m.group(1).strip()
        if target and target not in vtargets:
            vtargets.append(target)
    return vtargets


def ParseSourceFilename(nfilename):
    """从原始 PDF 文件名解析出 作者 / 年份 / 标题 / 引用key。"""
    name = re.sub(r"\.(pdf|md|txt|docx)$", "", nfilename, flags=re.IGNORECASE)
    author, year, title = "", "", name
    m = re.match(r"^(.*?),\s*(\d{4})\s*,\s*(.*)$", name)
    if m:
        author, year, title = m.group(1).strip(), m.group(2), m.group(3).strip()
    else:
        m = re.match(r"^(.*?)\s*-\s*(\d{4})\s*-\s*(.*)$", name)
        if m:
            author, year, title = m.group(1).strip(), m.group(2), m.group(3).strip()
    firstword = re.split(r"[\s,]+", author)[0].lower() if author else "src"
    key = (firstword + "-" + year) if year else firstword
    return {"key": key, "author": author, "year": year, "title": title, "filename": nfilename}


def BuildNodeIndex(vnodes):
    """构造 别名/标题/文件名 -> 节点id 的解析表，用于 wikilink 匹配。"""
    omap = {}
    for node in vnodes:
        for c in [node["id"], node.get("title", "")] + node.get("aliases", []):
            if c:
                omap[c.strip().lower()] = node["id"]
    return omap


def GetSummary(nbody):
    """取正文第一段非空、非标题文字作为摘要。"""
    for line in nbody.split("\n"):
        s = line.strip()
        if not s or s.startswith(("#", ">", "|", "---")):
            continue
        s = re.sub(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]", lambda m: m.group(2) or m.group(1), s)
        s = re.sub(r"[*_`]", "", s)
        return s[:160]
    return ""


def ListSources():
    """列出 raw/sources 下的原始文献文件名。"""
    if not os.path.isdir(rawsourcesdir):
        return []
    return [fn for fn in sorted(os.listdir(rawsourcesdir))
            if fn.lower().endswith((".pdf", ".docx", ".md", ".txt")) and not fn.startswith(".")]


def ScanWiki():
    """扫描 wiki 内容页与 purpose.md，返回节点与边。"""
    vnodes = []
    vrawlinks = []

    for fn in ListSources():
        ometa = ParseSourceFilename(fn)
        vnodes.append({
            "id": ometa["key"], "title": ometa["title"] or fn, "type": "source",
            "aliases": [], "authors": [ometa["author"]] if ometa["author"] else [],
            "year": ometa["year"], "venue": "", "tags": [], "rawfile": fn,
            "ingested": False, "summary": "尚未分析。点击「分析」即可生成结构化摘要与关联。",
        })

    skipfiles = {"index.md", "log.md", "overview.md"}
    for dirpath, _, filenames in os.walk(wikidir):
        for fn in sorted(filenames):
            if not fn.endswith(".md") or fn.startswith("_") or fn in skipfiles:
                continue
            with open(os.path.join(dirpath, fn), "r", encoding="utf-8") as f:
                ntext = f.read()
            ofm, nbody = ParseFrontmatter(ntext)
            nodeid = os.path.splitext(fn)[0]
            onode = {
                "id": nodeid, "title": ofm.get("title", nodeid), "type": ofm.get("type", "unknown"),
                "aliases": ofm.get("aliases", []) if isinstance(ofm.get("aliases", []), list) else [],
                "authors": ofm.get("authors", []) if isinstance(ofm.get("authors", []), list) else [],
                "year": ofm.get("year", ""), "venue": ofm.get("venue", ""),
                "tags": ofm.get("tags", []) if isinstance(ofm.get("tags", []), list) else [],
                "rawfile": "", "ingested": True, "summary": GetSummary(nbody),
            }
            existing = next((n for n in vnodes if n["id"] == nodeid), None)
            if existing:
                existing.update({k: v for k, v in onode.items() if v})
                existing["ingested"] = True
            else:
                vnodes.append(onode)
            for t in ExtractLinks(nbody):
                vrawlinks.append((nodeid, t))

    purposepath = os.path.join(rootdir, "purpose.md")
    if os.path.isfile(purposepath):
        with open(purposepath, "r", encoding="utf-8") as f:
            _, pbody = ParseFrontmatter(f.read())
        vnodes.append({
            "id": "purpose", "title": "论文目标 (Purpose)", "type": "purpose",
            "aliases": ["purpose"], "authors": [], "year": "", "venue": "",
            "tags": [], "rawfile": "", "ingested": True, "summary": GetSummary(pbody),
        })
        for t in ExtractLinks(pbody):
            vrawlinks.append(("purpose", t))

    onodeindex = BuildNodeIndex(vnodes)
    vedges = []
    vseen = set()
    for srcid, target in vrawlinks:
        tgtid = onodeindex.get(target.strip().lower())
        if not tgtid or tgtid == srcid:
            continue
        edgekey = tuple(sorted([srcid, tgtid]))
        if edgekey in vseen:
            continue
        vseen.add(edgekey)
        vedges.append({"source": srcid, "target": tgtid})
    return vnodes, vedges


def BuildData():
    vnodes, vedges = ScanWiki()
    odegree = {n["id"]: 0 for n in vnodes}
    for e in vedges:
        odegree[e["source"]] += 1
        odegree[e["target"]] += 1
    for n in vnodes:
        n["degree"] = odegree.get(n["id"], 0)
    ostats = {}
    for n in vnodes:
        ostats[n["type"]] = ostats.get(n["type"], 0) + 1
    return {
        "nodes": vnodes, "edges": vedges, "stats": ostats,
        "typeconfig": typeconfig, "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


def PendingSources():
    """返回尚未摄入（无对应 wiki/sources/<key>.md）的原始文献文件名。"""
    vnodes, _ = ScanWiki()
    omap = {n["id"]: n for n in vnodes}
    vpending = []
    for fn in ListSources():
        key = ParseSourceFilename(fn)["key"]
        node = omap.get(key)
        if not node or not node.get("ingested"):
            vpending.append(fn)
    return vpending


def GenerateIndex():
    """根据当前扫描结果自动重写 wiki/index.md（纯导航，安全覆盖）。"""
    vnodes, _ = ScanWiki()
    order = ["rq", "concept", "entity", "source", "experiment", "synthesis", "comparison", "query"]
    lines = ["---", "type: index", "title: Wiki 目录导航",
             "updated: %s" % datetime.now().strftime("%Y-%m-%d"), "---", "",
             "# Index · 内容目录", "",
             "> 由工具自动生成，每次添加/分析/刷新后更新。", ""]
    for t in order:
        items = [n for n in vnodes if n["type"] == t]
        if not items:
            continue
        lines.append("## %s（%d）" % (typeconfig[t]["label"], len(items)))
        lines.append("")
        for n in sorted(items, key=lambda x: x["id"]):
            tail = (" — %s" % n["title"]) if n["title"] and n["title"] != n["id"] else ""
            mark = "" if n.get("ingested", True) else "（待分析）"
            lines.append("- [[%s]]%s%s" % (n["id"], tail, mark))
        lines.append("")
    with open(os.path.join(wikidir, "index.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def AppendLog(nmessage):
    """向 wiki/log.md 追加一条带时间戳的审计记录。"""
    logpath = os.path.join(wikidir, "log.md")
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    line = "- [%s] %s\n" % (stamp, nmessage)
    if os.path.isfile(logpath):
        with open(logpath, "a", encoding="utf-8") as f:
            f.write(line)
    else:
        with open(logpath, "w", encoding="utf-8") as f:
            f.write("---\ntype: log\ntitle: 操作审计日志\n---\n\n# Log · 操作历史\n\n" + line)


def Render(odata, servermode=False):
    payload = json.dumps(odata, ensure_ascii=False)
    startcmd = os.path.join(rootdir, "start.command").replace("\\", "\\\\").replace('"', '\\"')
    return (HTMLTEMPLATE
            .replace("/*__DATA__*/", payload)
            .replace("/*__SERVERMODE__*/", "true" if servermode else "false")
            .replace("/*__STARTCMD__*/", startcmd))


HTMLTEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>博士论文 Wiki · 可视化</title>
<style>
  :root{--bg:#0f1115;--panel:#171a21;--panel2:#1e222b;--border:#2a2f3a;--text:#e6e9ef;--muted:#8b93a3;--accent:#4f9dde}
  *{box-sizing:border-box;margin:0;padding:0}
  body{background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;height:100vh;overflow:hidden;display:flex;flex-direction:column}
  header{padding:12px 22px;border-bottom:1px solid var(--border);display:flex;align-items:center;gap:14px;background:var(--panel);flex-wrap:wrap}
  header h1{font-size:16px;font-weight:600;white-space:nowrap}
  header .meta{color:var(--muted);font-size:12px}
  .toolbar{display:flex;gap:8px;align-items:center}
  .svc{display:inline-flex;align-items:center;gap:7px;cursor:pointer;user-select:none}
  .svc input{display:none}
  .svc .track{width:38px;height:20px;border-radius:20px;background:var(--panel2);border:1px solid var(--border);position:relative;transition:.2s}
  .svc .track::after{content:"";position:absolute;top:2px;left:2px;width:14px;height:14px;border-radius:50%;background:var(--muted);transition:.2s}
  .svc input:checked+.track{background:rgba(79,207,157,.25);border-color:#4fcf9d}
  .svc input:checked+.track::after{left:20px;background:#4fcf9d}
  .svc .svclbl{font-size:12px;color:var(--muted)}
  .tabs{display:flex;gap:6px;margin-left:auto}
  .tab{padding:7px 16px;border-radius:8px;cursor:pointer;font-size:13px;color:var(--muted);border:1px solid transparent}
  .tab:hover{background:var(--panel2)}
  .tab.active{background:var(--panel2);color:var(--text);border-color:var(--border)}
  main{flex:1;overflow:hidden;position:relative}
  .view{position:absolute;inset:0;display:none;overflow:auto;padding:22px}
  .view.active{display:block}
  #graphview.active{display:block;padding:0}
  .stats{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:20px}
  .statcard{background:var(--panel);border:1px solid var(--border);border-radius:10px;padding:12px 18px;min-width:90px}
  .statcard .num{font-size:22px;font-weight:600}
  .statcard .lbl{font-size:12px;color:var(--muted);margin-top:2px}
  .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:16px}
  .card{background:var(--panel);border:1px solid var(--border);border-radius:12px;padding:16px;transition:.15s;cursor:pointer;position:relative}
  .card:hover{border-color:var(--accent);transform:translateY(-2px)}
  .card .ttl{font-size:15px;font-weight:600;line-height:1.4;margin-bottom:8px;padding-right:20px}
  .card .sub{font-size:12px;color:var(--muted);margin-bottom:8px}
  .card .sum{font-size:13px;color:#c2c8d4;line-height:1.6}
  .card .del{position:absolute;top:10px;right:12px;color:var(--muted);cursor:pointer;font-size:16px;opacity:0}
  .card:hover .del{opacity:1}
  .card .del:hover{color:#de5f7a}
  .badge{display:inline-block;font-size:11px;padding:2px 8px;border-radius:6px;color:#0f1115;font-weight:600;margin-right:6px}
  .badge.soft{background:var(--panel2);color:var(--muted);font-weight:500}
  .tags{margin-top:10px}
  .pending{opacity:.78}
  .pending .ttl::after{content:" · 待分析";font-size:11px;color:var(--muted);font-weight:400}
  .typegroup{margin-bottom:24px}
  .typegroup h3{font-size:13px;color:var(--muted);margin-bottom:10px;text-transform:uppercase;letter-spacing:.5px}
  .listitem{display:flex;align-items:center;gap:10px;padding:9px 12px;border-radius:8px;cursor:pointer}
  .listitem:hover{background:var(--panel)}
  .dot{width:9px;height:9px;border-radius:50%;flex-shrink:0}
  #graphcanvas{display:block;width:100%;height:100%;cursor:grab}
  #graphcanvas:active{cursor:grabbing}
  .legend{position:absolute;left:18px;top:18px;background:rgba(23,26,33,.9);border:1px solid var(--border);border-radius:10px;padding:12px 14px;font-size:12px;backdrop-filter:blur(6px)}
  .legend .row{display:flex;align-items:center;gap:8px;margin:4px 0}
  .legend .dot{width:10px;height:10px}
  .hint{position:absolute;right:18px;bottom:18px;color:var(--muted);font-size:12px}
  #drawer{position:absolute;top:0;right:0;width:380px;height:100%;background:var(--panel);border-left:1px solid var(--border);transform:translateX(100%);transition:.25s;padding:22px;overflow:auto;z-index:10}
  #drawer.open{transform:translateX(0)}
  #drawer .close{position:absolute;top:14px;right:16px;cursor:pointer;color:var(--muted);font-size:20px;line-height:1}
  #drawer h2{font-size:18px;margin:6px 40px 12px 0;line-height:1.4}
  #drawer .field{margin:12px 0;font-size:13px}
  #drawer .field .k{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.5px;margin-bottom:3px}
  #drawer .links a{display:inline-block;margin:3px 6px 3px 0;padding:3px 9px;background:var(--panel2);border-radius:6px;font-size:12px;color:var(--accent);text-decoration:none;cursor:pointer}
  .empty{color:var(--muted);text-align:center;padding:60px 20px;font-size:14px;line-height:1.8}
  .btn{display:inline-flex;align-items:center;gap:6px;padding:7px 14px;border-radius:8px;font-size:13px;font-weight:600;cursor:pointer;border:1px solid var(--border);background:var(--accent);color:#0f1115;text-decoration:none;white-space:nowrap}
  .btn:hover{filter:brightness(1.1)}
  .btn.sec{background:var(--panel2);color:var(--text)}
  .btn.ghost{background:transparent;color:var(--accent)}
  .btn:disabled{opacity:.5;cursor:not-allowed}
  .pdfbtn{margin-top:10px;font-size:11px;padding:4px 10px;background:var(--panel2);color:var(--accent);border:1px solid var(--border);border-radius:6px;cursor:pointer}
  .pdfbtn:hover{border-color:var(--accent)}
  #pdfmodal,#setmodal,#startmodal{position:fixed;inset:0;background:rgba(0,0,0,.7);z-index:50;display:none;flex-direction:column;padding:24px}
  #pdfmodal.open,#setmodal.open,#startmodal.open{display:flex}
  #pdfmodal .bar{display:flex;align-items:center;gap:14px;padding:10px 14px;background:var(--panel);border:1px solid var(--border);border-radius:10px 10px 0 0}
  #pdfmodal .bar .name{font-size:13px;color:var(--text);flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  #pdfmodal .bar .x{cursor:pointer;color:var(--muted);font-size:22px;line-height:1}
  #pdfframe{flex:1;width:100%;border:1px solid var(--border);border-top:none;border-radius:0 0 10px 10px;background:#fff}
  #setmodal,#startmodal{align-items:center;justify-content:center}
  .setbox{background:var(--panel);border:1px solid var(--border);border-radius:14px;padding:26px;width:min(560px,92vw);max-height:88vh;overflow:auto}
  .setbox h2{font-size:17px;margin-bottom:6px}
  .setbox p.note{color:var(--muted);font-size:12px;margin-bottom:18px;line-height:1.7}
  .setbox label{display:block;font-size:12px;color:var(--muted);margin:14px 0 5px}
  .setbox input,.setbox select{width:100%;padding:9px 11px;border-radius:8px;border:1px solid var(--border);background:var(--panel2);color:var(--text);font-size:13px}
  .setbox .row{display:flex;gap:18px;justify-content:flex-end;margin-top:22px}
  #toast{position:fixed;left:50%;bottom:28px;transform:translateX(-50%) translateY(20px);background:var(--panel);border:1px solid var(--border);border-radius:10px;padding:12px 20px;font-size:13px;z-index:80;opacity:0;transition:.25s;pointer-events:none;max-width:80vw;box-shadow:0 8px 30px rgba(0,0,0,.4)}
  #toast.show{opacity:1;transform:translateX(-50%) translateY(0)}
  #overlay{position:fixed;inset:0;background:rgba(15,17,21,.78);z-index:70;display:none;flex-direction:column;align-items:center;justify-content:center;gap:18px}
  #overlay.open{display:flex}
  .spinner{width:42px;height:42px;border:4px solid var(--border);border-top-color:var(--accent);border-radius:50%;animation:spin 1s linear infinite}
  @keyframes spin{to{transform:rotate(360deg)}}
  #overlay .msg{font-size:14px;color:var(--text);max-width:70vw;text-align:center}
  #progwrap{width:300px;height:9px;background:var(--panel2);border:1px solid var(--border);border-radius:6px;overflow:hidden;display:none}
  #progwrap.show{display:block}
  #progbar{height:100%;width:0;background:var(--accent);transition:width .3s}
  #progtext{font-size:12px;color:var(--muted)}
</style>
</head>
<body>
<header>
  <h1>📚 博士论文 Wiki</h1>
  <label class="svc" title="本地服务开关"><input type="checkbox" id="svctoggle"><span class="track"></span><span class="svclbl" id="svclbl">服务</span></label>
  <div class="toolbar" id="toolbar">
    <button class="btn" onclick="AddPaper()">＋ 添加文献</button>
    <button class="btn sec" onclick="Analyze()">✨ 分析</button>
    <button class="btn sec" onclick="Refresh()">↻ 刷新</button>
    <button class="btn sec" onclick="OpenSettings()">⚙ 设置</button>
    <input type="file" id="fileinput" accept=".pdf,.docx,.md,.txt" multiple style="display:none">
  </div>
  <span class="meta" id="metainfo"></span>
  <div class="tabs">
    <div class="tab active" data-view="libview">论文库</div>
    <div class="tab" data-view="graphview">知识图谱</div>
    <div class="tab" data-view="listview">全部页面</div>
  </div>
</header>
<main>
  <section id="libview" class="view active"><div class="stats" id="statsbar"></div><div class="grid" id="libgrid"></div></section>
  <section id="graphview" class="view"><canvas id="graphcanvas"></canvas><div class="legend" id="legend"></div><div class="hint">滚轮缩放 · 拖拽平移 · 拖动节点 · 点击查看详情</div></section>
  <section id="listview" class="view"></section>
  <div id="drawer"><span class="close" onclick="CloseDrawer()">×</span><div id="drawerbody"></div></div>
  <div id="pdfmodal"><div class="bar"><span class="name" id="pdfname"></span><a class="btn ghost" id="pdfnewtab" target="_blank">在新标签打开 ↗</a><span class="x" onclick="ClosePdf()">×</span></div><iframe id="pdfframe"></iframe></div>
  <div id="setmodal"><div class="setbox">
    <h2>⚙ 设置 · 大模型 API</h2>
    <p class="note">填写后，点「分析」即可自动把文献摄入知识库。兼容 OpenAI 接口（OpenAI / DeepSeek / 通义 / Moonshot 等）。Key 仅保存在本机 <code>.paper-helper/config.json</code>，不会上传。</p>
    <label>API 地址（Base URL）</label>
    <input id="set_baseurl" placeholder="https://api.openai.com/v1">
    <label>API Key</label>
    <input id="set_apikey" type="password" placeholder="sk-...">
    <label>模型名称</label>
    <input id="set_model" placeholder="gpt-4o-mini">
    <label>输出语言</label>
    <select id="set_lang"><option value="中文">中文</option><option value="English">English</option></select>
    <div class="row"><button class="btn ghost" onclick="CloseSettings()">取消</button><button class="btn" onclick="SaveSettings()">保存</button></div>
  </div></div>
  <div id="startmodal"><div class="setbox">
    <h2>启动本地服务</h2>
    <p class="note">出于浏览器安全限制，网页无法直接启动本机程序。请用以下任一方式开启服务，开启后「添加 / 分析 / 刷新」即可使用：</p>
    <p style="font-size:13px;line-height:2">① 双击项目根目录的 <b>start.command</b><br>② 或复制下面命令到「终端」运行：</p>
    <input id="startcmdbox" readonly onclick="this.select()">
    <div class="row"><button class="btn ghost" onclick="CloseStart()">关闭</button><button class="btn" onclick="CopyStart()">复制命令</button></div>
  </div></div>
  <div id="overlay"><div class="spinner"></div><div class="msg" id="overlaymsg">处理中…</div><div id="progwrap"><div id="progbar"></div></div><div id="progtext"></div></div>
</main>
<div id="toast"></div>
<script>
const SERVERMODE = /*__SERVERMODE__*/;
let DATA = /*__DATA__*/;
let TC = DATA.typeconfig;
let NODEMAP = {};
function ReindexNodes(){NODEMAP={};DATA.nodes.forEach(n=>NODEMAP[n.id]=n)}
ReindexNodes();

function TypeLabel(t){return (TC[t]||TC.unknown).label}
function TypeColor(t){return (TC[t]||TC.unknown).color}
function Esc(s){return (s||"").replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}
function Attr(s){return (s||"").replace(/'/g,"\\'").replace(/"/g,"&quot;")}

/* ---------- 渲染 ---------- */
function RenderStats(){
  const order=["source","concept","entity","rq","experiment","synthesis","comparison","query"];
  let h=`<div class="statcard"><div class="num">${DATA.nodes.length}</div><div class="lbl">页面总数</div></div>`;
  h+=`<div class="statcard"><div class="num">${DATA.edges.length}</div><div class="lbl">关联数</div></div>`;
  order.forEach(t=>{if(DATA.stats[t])h+=`<div class="statcard"><div class="num">${DATA.stats[t]}</div><div class="lbl">${TypeLabel(t)}</div></div>`});
  document.getElementById("statsbar").innerHTML=h;
}
function RenderLibrary(){
  const sources=DATA.nodes.filter(n=>n.type==="source");
  const grid=document.getElementById("libgrid");
  if(!sources.length){grid.innerHTML='<div class="empty">论文库为空。<br>点击左上角「＋ 添加文献」上传 PDF。</div>';return}
  grid.innerHTML=sources.map(n=>{
    const authors=(n.authors||[]).filter(Boolean).join(", ");
    const sub=[authors,n.year,n.venue].filter(Boolean).join(" · ");
    const tags=(n.tags||[]).map(t=>`<span class="badge soft">${Esc(t)}</span>`).join("");
    const pdfbtn=IsPdf(n.rawfile)?`<button class="pdfbtn" onclick="event.stopPropagation();OpenPdf('${Attr(n.rawfile)}')">📄 打开 PDF</button>`:"";
    const del=(SERVERMODE&&n.rawfile)?`<span class="del" title="删除" onclick="event.stopPropagation();DeletePaper('${Attr(n.rawfile)}')">🗑</span>`:"";
    return `<div class="card ${n.ingested?'':'pending'}" onclick="OpenDrawer('${Attr(n.id)}')">
      ${del}<div class="ttl">${Esc(n.title)}</div>
      <div class="sub">${Esc(sub)||"—"}</div>
      <div class="sum">${Esc(n.summary||"")}</div>
      <div class="tags">${tags}</div>${pdfbtn}</div>`;
  }).join("");
}
function RenderList(){
  const v=document.getElementById("listview");
  const types=[...new Set(DATA.nodes.map(n=>n.type))];
  let h="";
  types.forEach(t=>{
    const items=DATA.nodes.filter(n=>n.type===t);
    h+=`<div class="typegroup"><h3>${TypeLabel(t)} (${items.length})</h3>`;
    items.forEach(n=>{h+=`<div class="listitem" onclick="OpenDrawer('${Attr(n.id)}')"><span class="dot" style="background:${TypeColor(t)}"></span><span>${Esc(n.title)}</span></div>`});
    h+=`</div>`;
  });
  v.innerHTML=h||'<div class="empty">暂无页面。</div>';
}
function RenderAll(){
  TC=DATA.typeconfig;ReindexNodes();
  RenderStats();RenderLibrary();RenderList();
  document.getElementById("metainfo").textContent=(SERVERMODE?"本地服务 · ":"")+"更新于 "+DATA.generated;
  if(canvas&&document.getElementById("graphview").classList.contains("active"))InitGraph();
  else canvas=null;
}

/* ---------- 详情抽屉 ---------- */
function NeighborsOf(id){const ns=new Set();DATA.edges.forEach(e=>{if(e.source===id)ns.add(e.target);if(e.target===id)ns.add(e.source)});return [...ns]}
function OpenDrawer(id){
  const n=NODEMAP[id];if(!n)return;
  const authors=(n.authors||[]).filter(Boolean).join(", ");
  const sub=[authors,n.year,n.venue].filter(Boolean).join(" · ");
  const neigh=NeighborsOf(id);
  let h=`<div><span class="badge" style="background:${TypeColor(n.type)}">${TypeLabel(n.type)}</span></div><h2>${Esc(n.title)}</h2>`;
  if(sub)h+=`<div class="field"><div class="k">信息</div>${Esc(sub)}</div>`;
  if(n.rawfile)h+=`<div class="field"><div class="k">原始文件</div>${Esc(n.rawfile)}</div>`;
  if(IsPdf(n.rawfile))h+=`<div class="field"><button class="btn" onclick="OpenPdf('${Attr(n.rawfile)}')">📄 在浏览器中打开 PDF</button></div>`;
  if(n.summary)h+=`<div class="field"><div class="k">摘要</div>${Esc(n.summary)}</div>`;
  if((n.tags||[]).length)h+=`<div class="field"><div class="k">标签</div>${n.tags.map(t=>`<span class="badge soft">${Esc(t)}</span>`).join("")}</div>`;
  if(neigh.length)h+=`<div class="field links"><div class="k">关联页面 (${neigh.length})</div>${neigh.map(x=>`<a onclick="OpenDrawer('${Attr(x)}')">${Esc((NODEMAP[x]||{}).title||x)}</a>`).join("")}</div>`;
  if(!n.ingested&&n.rawfile)h+=`<div class="field"><button class="btn" onclick="Analyze('${Attr(n.rawfile)}')">✨ 分析这篇文献</button></div>`;
  document.getElementById("drawerbody").innerHTML=h;
  document.getElementById("drawer").classList.add("open");
}
function CloseDrawer(){document.getElementById("drawer").classList.remove("open")}

/* ---------- PDF 预览 ---------- */
function IsPdf(f){return f&&/\.pdf$/i.test(f)}
function PdfHref(f){return "raw/sources/"+encodeURIComponent(f)}
function OpenPdf(f){const href=PdfHref(f);document.getElementById("pdfname").textContent=f;document.getElementById("pdfframe").src=href;document.getElementById("pdfnewtab").href=href;document.getElementById("pdfmodal").classList.add("open")}
function ClosePdf(){document.getElementById("pdfmodal").classList.remove("open");document.getElementById("pdfframe").src=""}
document.addEventListener("keydown",e=>{if(e.key==="Escape"){ClosePdf();CloseDrawer();CloseSettings();CloseStart()}});

/* ---------- 服务开关 ---------- */
const STARTCMD="/*__STARTCMD__*/";
let serverUp=SERVERMODE;
function InitSvcToggle(){
  const t=document.getElementById("svctoggle");
  t.checked=serverUp;
  document.getElementById("svclbl").textContent=serverUp?"运行中":"已停止";
  t.onchange=()=>{
    if(serverUp){t.checked=true;StopService();}      // 真正停止
    else{t.checked=false;OpenStart();}                // 浏览器无法启动，给引导
  };
}
async function StopService(){
  if(!confirm("确定停止本地服务？\n停止后将无法添加/分析，需重新双击 start.command 启动。"))return;
  try{await Api("/api/shutdown",{});}catch(e){}
  serverUp=false;
  document.getElementById("svctoggle").checked=false;
  document.getElementById("svclbl").textContent="已停止";
  document.getElementById("toolbar").innerHTML='<span class="meta">📖 服务已停止 · 双击 start.command 重新启动</span>';
  Toast("服务已停止");
}
function OpenStart(){document.getElementById("startcmdbox").value='bash "'+STARTCMD+'"';document.getElementById("startmodal").classList.add("open")}
function CloseStart(){document.getElementById("startmodal").classList.remove("open")}
function CopyStart(){const b=document.getElementById("startcmdbox");b.select();try{document.execCommand("copy")}catch(e){}if(navigator.clipboard)navigator.clipboard.writeText(b.value).catch(()=>{});Toast("已复制启动命令")}

/* ---------- 工具栏动作 ---------- */
function Toast(msg,ms){const t=document.getElementById("toast");t.textContent=msg;t.classList.add("show");clearTimeout(t._t);t._t=setTimeout(()=>t.classList.remove("show"),ms||3000)}
function ShowOverlay(msg){document.getElementById("overlaymsg").textContent=msg||"处理中…";document.getElementById("overlay").classList.add("open")}
function HideOverlay(){document.getElementById("overlay").classList.remove("open")}
function NeedServer(){if(!SERVERMODE){Toast("此功能需双击 start.command 启动本地服务后使用");return true}return false}

async function Api(path,body){
  const opt={method:body?"POST":"GET",headers:{"Content-Type":"application/json"}};
  if(body)opt.body=JSON.stringify(body);
  const r=await fetch(path,opt);
  if(!r.ok)throw new Error("HTTP "+r.status);
  return r.json();
}
async function Refresh(silent){
  if(!SERVERMODE){if(!silent)Toast("静态页面：请重跑 build_site.py 刷新");return}
  try{DATA=await Api("/api/data");RenderAll();if(!silent)Toast("已刷新")}catch(e){Toast("刷新失败："+e.message)}
}
function AddPaper(){if(NeedServer())return;document.getElementById("fileinput").click()}
document.getElementById("fileinput").onchange=async function(){
  const files=[...this.files];this.value="";
  if(!files.length)return;
  ShowOverlay(`正在上传 ${files.length} 个文件…`);
  try{
    for(const f of files){
      const b64=await FileToBase64(f);
      await Api("/api/upload",{name:f.name,data:b64});
    }
    await Refresh(true);
    HideOverlay();Toast(`已添加 ${files.length} 篇文献，点「分析」生成知识页`);
  }catch(e){HideOverlay();Toast("上传失败："+e.message)}
};
function FileToBase64(file){return new Promise((res,rej)=>{const r=new FileReader();r.onload=()=>res(r.result.split(",")[1]);r.onerror=rej;r.readAsDataURL(file)})}

async function DeletePaper(rawfile){
  if(NeedServer())return;
  if(!confirm("确定删除该文献及其知识页？\n"+rawfile))return;
  ShowOverlay("正在删除…");
  try{await Api("/api/delete",{rawfile});await Refresh(true);HideOverlay();Toast("已删除")}
  catch(e){HideOverlay();Toast("删除失败："+e.message)}
}
let polltimer=null;
function ShortName(s){return (s||"").length>34?s.slice(0,33)+"…":s}
async function Analyze(rawfile){
  if(NeedServer())return;
  try{
    const res=await Api("/api/ingest",{rawfile:rawfile||null});
    if(res.status==="need_key"){Toast(`未配置 API Key，有 ${res.pending||0} 篇待分析。请在「设置」中填写后再点分析。`,5000);OpenSettings();return}
    if(res.status==="no_pending"){Toast("没有待分析的文献");return}
    StartProgressUI(res.total||1);  // started 或 running 都进入进度轮询
    PollProgress();
  }catch(e){Toast("分析失败："+e.message,5000)}
}
function StartProgressUI(total){
  ShowOverlay("正在分析…");
  const w=document.getElementById("progwrap");w.classList.add("show");
  document.getElementById("progbar").style.width="0%";
  document.getElementById("progtext").textContent="0 / "+total;
}
async function PollProgress(){
  try{
    const p=await Api("/api/ingest/progress");
    const total=p.total||1,done=p.done||0;
    document.getElementById("progbar").style.width=Math.round(done/total*100)+"%";
    document.getElementById("progtext").textContent=`${done} / ${total}`+(p.current?(" · "+ShortName(p.current)):"");
    document.getElementById("overlaymsg").textContent=p.current?("正在分析："+ShortName(p.current)):"正在分析…";
    if(p.running){polltimer=setTimeout(PollProgress,1500);return}
    FinishProgress(p);
  }catch(e){FinishProgress(null);Toast("进度获取失败："+e.message,4000)}
}
function FinishProgress(p){
  if(polltimer){clearTimeout(polltimer);polltimer=null}
  document.getElementById("progwrap").classList.remove("show");
  HideOverlay();
  Refresh(true);CloseDrawer();
  if(p){let msg=`完成：成功 ${p.ingested?p.ingested.length:0} 篇`;if(p.failed&&p.failed.length)msg+=`，失败 ${p.failed.length} 篇`;Toast(msg,5000)}
}

/* ---------- 设置 ---------- */
async function OpenSettings(){
  if(NeedServer())return;
  try{const c=await Api("/api/config");
    document.getElementById("set_baseurl").value=c.base_url||"https://api.openai.com/v1";
    document.getElementById("set_apikey").value=c.api_key||"";
    document.getElementById("set_model").value=c.model||"gpt-4o-mini";
    document.getElementById("set_lang").value=c.language||"中文";
  }catch(e){}
  document.getElementById("setmodal").classList.add("open");
}
function CloseSettings(){document.getElementById("setmodal").classList.remove("open")}
async function SaveSettings(){
  const body={base_url:document.getElementById("set_baseurl").value.trim(),api_key:document.getElementById("set_apikey").value.trim(),model:document.getElementById("set_model").value.trim(),language:document.getElementById("set_lang").value};
  try{await Api("/api/config",body);CloseSettings();Toast("设置已保存")}catch(e){Toast("保存失败："+e.message)}
}

/* ---------- 力导向知识图谱 ---------- */
let canvas,ctx,nodes=[],links=[],view={x:0,y:0,scale:1},dragnode=null,dragging=false,last={x:0,y:0},hover=null,rafid=null;
function InitGraph(){
  canvas=document.getElementById("graphcanvas");ctx=canvas.getContext("2d");ResizeCanvas();
  const w=canvas.clientWidth,hh=canvas.clientHeight;
  nodes=DATA.nodes.map((n,i)=>({...n,x:w/2+Math.cos(i/DATA.nodes.length*6.28)*150+(Math.random()-.5)*40,y:hh/2+Math.sin(i/DATA.nodes.length*6.28)*150+(Math.random()-.5)*40,vx:0,vy:0,r:7+Math.min(n.degree*2.5,16)}));
  const nm={};nodes.forEach(n=>nm[n.id]=n);
  links=DATA.edges.map(e=>({s:nm[e.source],t:nm[e.target]})).filter(l=>l.s&&l.t);
  RenderLegend();BindGraph();if(rafid)cancelAnimationFrame(rafid);Simulate();
}
function ResizeCanvas(){const dpr=window.devicePixelRatio||1;canvas.width=canvas.clientWidth*dpr;canvas.height=canvas.clientHeight*dpr;ctx.setTransform(dpr,0,0,dpr,0,0)}
function RenderLegend(){const used=[...new Set(DATA.nodes.map(n=>n.type))];document.getElementById("legend").innerHTML=used.map(t=>`<div class="row"><span class="dot" style="background:${TypeColor(t)}"></span>${TypeLabel(t)}</div>`).join("")}
function Simulate(){
  const w=canvas.clientWidth,hh=canvas.clientHeight,cx=w/2,cy=hh/2;
  for(let i=0;i<nodes.length;i++){const a=nodes[i];a.vx+=(cx-a.x)*0.0008;a.vy+=(cy-a.y)*0.0008;
    for(let j=i+1;j<nodes.length;j++){const b=nodes[j];let dx=a.x-b.x,dy=a.y-b.y,d2=dx*dx+dy*dy||1,d=Math.sqrt(d2);const f=2200/d2;dx/=d;dy/=d;a.vx+=dx*f;a.vy+=dy*f;b.vx-=dx*f;b.vy-=dy*f}}
  links.forEach(l=>{let dx=l.t.x-l.s.x,dy=l.t.y-l.s.y,d=Math.sqrt(dx*dx+dy*dy)||1;const f=(d-110)*0.01;dx/=d;dy/=d;l.s.vx+=dx*f;l.s.vy+=dy*f;l.t.vx-=dx*f;l.t.vy-=dy*f});
  nodes.forEach(n=>{if(n===dragnode)return;n.vx*=0.85;n.vy*=0.85;n.x+=n.vx;n.y+=n.vy});
  DrawGraph();rafid=requestAnimationFrame(Simulate);
}
function DrawGraph(){
  ctx.clearRect(0,0,canvas.clientWidth,canvas.clientHeight);ctx.save();ctx.translate(view.x,view.y);ctx.scale(view.scale,view.scale);
  const hoverNeigh=hover?new Set(NeighborsOf(hover.id)):null;
  links.forEach(l=>{const active=hover&&(l.s.id===hover.id||l.t.id===hover.id);ctx.strokeStyle=active?"rgba(79,157,222,.8)":"rgba(255,255,255,.10)";ctx.lineWidth=active?2:1;ctx.beginPath();ctx.moveTo(l.s.x,l.s.y);ctx.lineTo(l.t.x,l.t.y);ctx.stroke()});
  nodes.forEach(n=>{const dim=hover&&n!==hover&&!(hoverNeigh&&hoverNeigh.has(n.id));ctx.globalAlpha=dim?0.25:1;ctx.beginPath();ctx.arc(n.x,n.y,n.r,0,6.2832);ctx.fillStyle=TypeColor(n.type);ctx.fill();
    if(!n.ingested){ctx.lineWidth=1.5;ctx.strokeStyle="rgba(255,255,255,.5)";ctx.setLineDash([3,3]);ctx.stroke();ctx.setLineDash([])}
    if(view.scale>0.6||n.degree>1||n===hover){ctx.globalAlpha=dim?0.3:1;ctx.fillStyle="#e6e9ef";ctx.font="12px -apple-system,sans-serif";ctx.textAlign="center";const lbl=n.title.length>16?n.title.slice(0,15)+"…":n.title;ctx.fillText(lbl,n.x,n.y+n.r+13)}});
  ctx.globalAlpha=1;ctx.restore();
}
function ToWorld(e){const r=canvas.getBoundingClientRect();return{x:(e.clientX-r.left-view.x)/view.scale,y:(e.clientY-r.top-view.y)/view.scale}}
function PickNode(p){return nodes.find(n=>{const dx=n.x-p.x,dy=n.y-p.y;return dx*dx+dy*dy<=n.r*n.r+25})}
function BindGraph(){
  canvas.onmousedown=e=>{const p=ToWorld(e);dragnode=PickNode(p);dragging=true;last={x:e.clientX,y:e.clientY}};
  canvas.onmousemove=e=>{const p=ToWorld(e);hover=PickNode(p);canvas.style.cursor=hover?"pointer":"grab";if(!dragging)return;if(dragnode){dragnode.x=p.x;dragnode.y=p.y;dragnode.vx=0;dragnode.vy=0}else{view.x+=e.clientX-last.x;view.y+=e.clientY-last.y;last={x:e.clientX,y:e.clientY}}};
  canvas.onmouseup=e=>{if(dragnode&&Math.abs(e.clientX-last.x)<3&&Math.abs(e.clientY-last.y)<3)OpenDrawer(dragnode.id);dragging=false;dragnode=null};
  canvas.onwheel=e=>{e.preventDefault();const f=e.deltaY<0?1.1:0.9;const r=canvas.getBoundingClientRect();const mx=e.clientX-r.left,my=e.clientY-r.top;view.x=mx-(mx-view.x)*f;view.y=my-(my-view.y)*f;view.scale*=f};
  window.onresize=()=>{if(document.getElementById("graphview").classList.contains("active"))ResizeCanvas()};
}
document.querySelectorAll(".tab").forEach(tab=>{tab.onclick=()=>{
  document.querySelectorAll(".tab").forEach(t=>t.classList.remove("active"));
  document.querySelectorAll(".view").forEach(v=>v.classList.remove("active"));
  tab.classList.add("active");document.getElementById(tab.dataset.view).classList.add("active");
  if(tab.dataset.view==="graphview"){if(!canvas)InitGraph();else ResizeCanvas()}
}});

if(!SERVERMODE)document.getElementById("toolbar").innerHTML='<span class="meta">📖 只读模式 · 要添加/分析文献，请双击项目根目录的 <b>start.command</b> 启动</span>';
InitSvcToggle();
RenderAll();
if(SERVERMODE)Refresh(true);
</script>
</body>
</html>
"""


def Main():
    odata = BuildData()
    with open(outputpath, "w", encoding="utf-8") as f:
        f.write(Render(odata, servermode=False))
    print("已生成: %s" % outputpath)
    print("页面 %d 个，关联 %d 条" % (len(odata["nodes"]), len(odata["edges"])))


if __name__ == "__main__":
    Main()
