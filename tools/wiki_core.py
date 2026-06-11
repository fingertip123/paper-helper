#!/usr/bin/env python3
"""Wiki 公共核心：扫描 wiki/raw、构造可视化数据、生成 index、渲染 HTML 页面。

被 build_site.py（生成静态页）与 app.py（本地服务）共同复用，避免逻辑重复。
"""

import os
import re
import sys
import json
import shutil
from datetime import datetime

def ResolveRootDir():
    """开发态返回项目根目录；打包态返回用户主目录下的可写数据目录。

    打包成 .app/.exe 后，程序自身位于只读 bundle 内，wiki/raw 等需读写的
    内容必须放到用户可写位置；首次运行从内置模板（seed）播种一份初始内容。
    """
    if not getattr(sys, "frozen", False):
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ndatadir = os.path.join(os.path.expanduser("~"), "PaperHelper")
    nseed = os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(sys.executable)), "seed")
    if not os.path.exists(ndatadir) and os.path.isdir(nseed):
        shutil.copytree(nseed, ndatadir)
    for nsub in ("", "wiki", "wiki/sources", "raw", "raw/sources", "raw/assets"):
        os.makedirs(os.path.join(ndatadir, nsub), exist_ok=True)
    return ndatadir


rootdir = ResolveRootDir()

import topic_manager as topics  # noqa: E402
import wiki_ops as wops  # noqa: E402

topics.Init(rootdir)


def ReloadTopicPaths():
    """切换选题后刷新 wiki/raw 路径。"""
    global wikidir, rawsourcesdir
    nactive = topics.GetTopicDir()
    wikidir = os.path.join(nactive, "wiki")
    rawsourcesdir = os.path.join(nactive, "raw", "sources")
    os.makedirs(wikidir, exist_ok=True)
    os.makedirs(rawsourcesdir, exist_ok=True)
    wops.Init(wikidir, rawsourcesdir, rootdir)


ReloadTopicPaths()

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


def SourceMetaPath():
    return os.path.join(topics.GetTopicDir(), ".paper-helper", "source_meta.json")


def ReadSourceMeta():
    spath = SourceMetaPath()
    if not os.path.isfile(spath):
        return {}
    with open(spath, "r", encoding="utf-8") as f:
        return json.load(f)


def WriteSourceMeta(odata):
    spath = SourceMetaPath()
    os.makedirs(os.path.dirname(spath), exist_ok=True)
    with open(spath, "w", encoding="utf-8") as f:
        json.dump(odata, f, ensure_ascii=False, indent=2)


def NormalizeUrl(surl):
    surl = (surl or "").strip()
    if not surl:
        return ""
    if not re.match(r"^https?://", surl, re.I):
        raise ValueError("链接须以 http:// 或 https:// 开头")
    return surl


def GetPendingSourceUrl(srawfile):
    return ReadSourceMeta().get(srawfile, {}).get("url", "")


def SetPendingSourceUrl(srawfile, surl):
    ometa = ReadSourceMeta()
    if surl:
        ometa[srawfile] = {"url": surl}
    elif srawfile in ometa:
        del ometa[srawfile]
    WriteSourceMeta(ometa)


def FindSourcePagePath(skey):
    spath = os.path.join(wikidir, "sources", skey + ".md")
    return spath if os.path.isfile(spath) else ""


def UpdateSourceFrontmatterUrl(spath, surl):
    with open(spath, "r", encoding="utf-8") as f:
        ntext = f.read()
    if not frontmatterpattern.match(ntext):
        return
    if re.search(r"^url:\s*", ntext, re.MULTILINE):
        if surl:
            ntext = re.sub(r"^url:\s*.+$", "url: %s" % surl, ntext, count=1, flags=re.MULTILINE)
        else:
            ntext = re.sub(r"^url:\s*.+\n", "", ntext, count=1, flags=re.MULTILINE)
    elif surl:
        ntext = re.sub(r"^(---\s*\n.*?)(---\s*\n)", r"\1url: %s\n\2" % surl, ntext, count=1, flags=re.DOTALL)
    with open(spath, "w", encoding="utf-8") as f:
        f.write(ntext)


def SetPaperUrl(surl, srawfile=None, skey=None):
    surl = NormalizeUrl(surl) if surl else ""
    if not skey and srawfile:
        skey = ParseSourceFilename(srawfile)["key"]
    spath = FindSourcePagePath(skey) if skey else ""
    if spath:
        UpdateSourceFrontmatterUrl(spath, surl)
    if srawfile:
        SetPendingSourceUrl(srawfile, surl)
    return {"id": skey or "", "rawfile": srawfile or "", "url": surl}


def MergePendingUrlToSource(nfilename, skey=None):
    surl = GetPendingSourceUrl(nfilename)
    if not surl:
        return
    skey = skey or ParseSourceFilename(nfilename)["key"]
    spath = FindSourcePagePath(skey)
    if spath:
        UpdateSourceFrontmatterUrl(spath, surl)


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
            "url": GetPendingSourceUrl(fn),
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
                "url": ofm.get("url", ""),
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

    purposepath = topics.RulePath("purpose.md")
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
    try:
        wops.Init(wikidir, rawsourcesdir, rootdir)
        wops.GenerateOverview()
    except Exception:
        pass


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


def Render(odata, servermode=False, desktopmode=False):
    payload = json.dumps(odata, ensure_ascii=False)
    startcmd = os.path.join(rootdir, "start.command").replace("\\", "\\\\").replace('"', '\\"')
    otopicsinit = {"topics": [], "current": ""}
    if servermode:
        otopicsinit = {
            "topics": topics.ListTopics(),
            "current": topics.GetCurrentTopicId() or "",
            "purpose_fields": topics.GetPurposeFieldDefs(),
        }
    stopicsinit = json.dumps(otopicsinit, ensure_ascii=False)
    return (HTMLTEMPLATE
            .replace("/*__DATA__*/", payload)
            .replace("/*__INIT_TOPICS__*/", stopicsinit)
            .replace("/*__SERVERMODE__*/", "true" if servermode else "false")
            .replace("/*__DESKTOPMODE__*/", "true" if desktopmode else "false")
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
  .headbrand{display:flex;flex-direction:column;gap:5px;min-width:180px;max-width:min(520px,46vw)}
  header h1{font-size:16px;font-weight:600;white-space:nowrap}
  .curtopic{display:flex;align-items:baseline;gap:8px;min-width:0}
  .curtopic-lbl{font-size:11px;color:var(--muted);white-space:nowrap;flex-shrink:0;padding:2px 8px;border-radius:6px;background:var(--panel2);border:1px solid var(--border)}
  .curtopic-title{font-size:14px;font-weight:600;color:var(--accent);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0}
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
  .pdfbtn,.urlbtn{margin-top:10px;margin-right:8px;font-size:11px;padding:4px 10px;background:var(--panel2);color:var(--accent);border:1px solid var(--border);border-radius:6px;cursor:pointer;text-decoration:none;display:inline-block}
  .pdfbtn:hover,.urlbtn:hover{border-color:var(--accent)}
  .urledit{display:flex;gap:8px;align-items:center}
  .urledit input{flex:1;min-width:0;padding:7px 10px;border-radius:8px;border:1px solid var(--border);background:var(--panel2);color:var(--text);font-size:12px}
  #pdfmodal,#setmodal,#startmodal,#rulesmodal,#topicmodal,#querymodal,#lintmodal{position:fixed;inset:0;background:rgba(0,0,0,.7);z-index:50;display:none;flex-direction:column;padding:24px}
  #pdfmodal.open,#setmodal.open,#startmodal.open,#rulesmodal.open,#topicmodal.open,#querymodal.open,#lintmodal.open{display:flex}
  #pdfmodal .bar{display:flex;align-items:center;gap:14px;padding:10px 14px;background:var(--panel);border:1px solid var(--border);border-radius:10px 10px 0 0}
  #pdfmodal .bar .name{font-size:13px;color:var(--text);flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  #pdfmodal .bar .x{cursor:pointer;color:var(--muted);font-size:22px;line-height:1}
  #pdfframe{flex:1;width:100%;border:1px solid var(--border);border-top:none;border-radius:0 0 10px 10px;background:#fff}
  #setmodal,#startmodal,#rulesmodal,#topicmodal,#querymodal,#lintmodal{align-items:center;justify-content:center}
  .setbox{background:var(--panel);border:1px solid var(--border);border-radius:14px;padding:26px;width:min(560px,92vw);max-height:88vh;overflow:auto}
  .setbox-flex{display:flex;flex-direction:column;padding:0;overflow:hidden}
  .setbox-head{padding:22px 26px 0;flex-shrink:0}
  .setbox-body{padding:8px 26px 12px;overflow-y:auto;flex:1;min-height:0}
  .setbox-foot{padding:14px 26px 20px;border-top:1px solid var(--border);flex-shrink:0;display:flex;gap:12px;justify-content:flex-end;background:var(--panel);border-radius:0 0 14px 14px}
  .setbox h2{font-size:17px;margin-bottom:6px}
  .setbox p.note{color:var(--muted);font-size:12px;margin-bottom:12px;line-height:1.7}
  .setbox label{display:block;font-size:12px;color:var(--muted);margin:14px 0 5px}
  .setbox input,.setbox select{width:100%;padding:9px 11px;border-radius:8px;border:1px solid var(--border);background:var(--panel2);color:var(--text);font-size:13px;box-sizing:border-box}
  .setbox .row{display:flex;gap:12px;justify-content:flex-end;margin-top:22px}
  .reqtag{color:#de5f7a;margin-left:4px}
  .opttag{color:var(--muted);font-size:11px;margin-left:4px;font-weight:400}
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
  #overlay .cancelbtn{margin-top:8px}
  .dropzone{border:2px dashed var(--border);border-radius:12px;padding:28px;text-align:center;color:var(--muted);font-size:13px;margin-bottom:16px;transition:.15s}
  .dropzone.drag{border-color:var(--accent);background:rgba(79,157,222,.08);color:var(--text)}
  .graphfilter{position:absolute;right:18px;top:18px;background:rgba(23,26,33,.9);border:1px solid var(--border);border-radius:10px;padding:10px 12px;font-size:12px;z-index:2}
  .graphfilter select{padding:5px 8px;border-radius:6px;background:var(--panel2);border:1px solid var(--border);color:var(--text)}
  .lintlist{font-size:12px;line-height:1.7;color:var(--text)}
  .lintlist li{margin:4px 0}
  .queryans{white-space:pre-wrap;line-height:1.7;font-size:13px;max-height:40vh;overflow:auto;padding:12px;background:var(--panel2);border-radius:8px;border:1px solid var(--border)}
  .topicbar{display:flex;align-items:center;gap:8px;flex-wrap:wrap;width:100%;margin:6px 0 2px}
  .topicbar .lbl{font-size:12px;color:var(--muted)}
  .topicpick{position:relative;min-width:180px;max-width:280px;flex:0 1 280px}
  .topicpick-btn{width:100%;display:flex;align-items:center;gap:6px;padding:6px 10px;border-radius:8px;background:var(--panel2);border:1px solid var(--border);color:var(--text);font-size:13px;cursor:pointer;text-align:left}
  .topicpick-btn:hover{border-color:var(--accent)}
  .topicpick-lbl{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0}
  .topicpick-caret{color:var(--muted);font-size:10px;flex-shrink:0}
  .topicpick-menu{position:absolute;top:calc(100% + 4px);left:0;right:0;background:var(--panel);border:1px solid var(--border);border-radius:8px;box-shadow:0 8px 24px rgba(0,0,0,.45);max-height:240px;overflow-y:auto;z-index:100;display:none}
  .topicpick.open .topicpick-menu{display:block}
  .topicpick-item{padding:8px 12px;font-size:13px;cursor:pointer;overflow:hidden;white-space:nowrap}
  .topicpick-item:hover,.topicpick-item.active{background:var(--panel2)}
  .topicpick-item.active{color:var(--accent);font-weight:600}
  .topicpick-item .topicpick-text{display:inline-block;white-space:nowrap;will-change:transform}
  #rulesmodal,#topicmodal{align-items:center;justify-content:center}
  .ruletabs{display:flex;gap:8px;margin-bottom:12px;flex-wrap:wrap}
  .ruletab{padding:6px 14px;border-radius:8px;cursor:pointer;border:1px solid var(--border);font-size:12px;color:var(--text)}
  .ruletab.active{background:var(--accent);color:#0f1115;border-color:var(--accent)}
  .purposeform label{display:block;font-size:12px;color:var(--muted);margin:10px 0 4px}
  .purposeform input,.purposeform textarea{width:100%;padding:8px 10px;border-radius:8px;border:1px solid var(--border);background:var(--panel2);color:var(--text);font-size:13px;box-sizing:border-box}
  .purposeform textarea{min-height:68px;resize:vertical;font-family:inherit}
  .refbar{display:flex;flex-direction:column;align-items:stretch;margin-bottom:10px;gap:8px}
  .refbar .refpick{display:flex;align-items:center;gap:8px;width:100%}
  .refbar select.refselect{flex:1;min-width:0;padding:7px 10px;border-radius:8px;border:1px solid var(--border);background:var(--panel2);color:var(--text);font-size:13px}
  .refbar .btn{flex-shrink:0}
  #topicmodal .setbox-flex{max-height:min(90vh,820px)}
  #rulesmodal .setbox-flex{width:min(720px,96vw);height:min(90vh,820px);max-height:min(90vh,820px)}
  #topicmodal .setbox-body,#rulesmodal .setbox-body{padding-top:4px}
  #rulesmodal .setbox-body{flex:1;min-height:0;overflow:hidden;position:relative}
  #topicmodal .setbox-head p.note,#rulesmodal .setbox-head p.note{margin-bottom:10px}
  .rule-panel{position:absolute;inset:0;overflow-y:auto;display:none}
  .rule-panel.active{display:block}
  #rulesmodal .ruleseditor{width:100%;height:100%;min-height:0;padding:10px;border-radius:8px;border:1px solid var(--border);background:var(--panel2);color:var(--text);font-size:12px;font-family:ui-monospace,monospace;resize:none;box-sizing:border-box}
  .ruleseditor{width:100%;min-height:280px;padding:10px;border-radius:8px;border:1px solid var(--border);background:var(--panel2);color:var(--text);font-size:12px;font-family:ui-monospace,monospace;resize:vertical;box-sizing:border-box}
  .setbox-flex .purposeform label:first-child{margin-top:4px}
</style>
</head>
<body>
<header>
  <div class="headbrand">
    <h1>📚 博士论文 Wiki</h1>
    <div class="curtopic" id="curtopic">
      <span class="curtopic-lbl">当前选题</span>
      <span class="curtopic-title" id="curtopic_title">加载中…</span>
    </div>
  </div>
  <div class="topicbar" id="topicbar">
    <span class="lbl">选题</span>
    <div class="topicpick" id="topic_pick">
      <button type="button" class="topicpick-btn" id="topic_pick_btn" onclick="ToggleTopicMenu(event)">
        <span class="topicpick-lbl" id="topic_pick_lbl"></span>
        <span class="topicpick-caret">▾</span>
      </button>
      <div class="topicpick-menu" id="topic_pick_menu"></div>
    </div>
    <button class="btn sec" onclick="OpenNewTopic()">＋ 新选题</button>
    <button class="btn sec" onclick="ResetTopic()">↺ 重置</button>
    <button class="btn sec" onclick="OpenRules()">📋 研究规则</button>
  </div>
  <label class="svc" title="本地服务开关"><input type="checkbox" id="svctoggle"><span class="track"></span><span class="svclbl" id="svclbl">服务</span></label>
  <div class="toolbar" id="toolbar">
    <button class="btn" onclick="AddPaper()">＋ 添加文献</button>
    <button class="btn sec" onclick="Analyze()">✨ 分析</button>
    <button class="btn sec" onclick="OpenQuery()">💬 查询</button>
    <button class="btn sec" onclick="RunLint()">🩺 巡检</button>
    <button class="btn sec" onclick="Refresh()">↻ 刷新</button>
    <button class="btn sec" onclick="OpenSettings()">⚙ 设置</button>
    <button class="btn sec" onclick="ExportBib()">📤 BibTeX</button>
    <button class="btn sec" onclick="SnapshotTopic()">💾 备份</button>
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
  <section id="libview" class="view active"><div class="stats" id="statsbar"></div><div class="dropzone" id="dropzone">拖放 PDF / Word / Markdown 到此处上传，或点击左上角「＋ 添加文献」</div><div class="grid" id="libgrid"></div></section>
  <section id="graphview" class="view"><canvas id="graphcanvas"></canvas><div class="legend" id="legend"></div><div class="graphfilter"><label>筛选 </label><select id="graph_filter" onchange="ApplyGraphFilter()"><option value="">全部类型</option></select></div><div class="hint">滚轮缩放 · 拖拽平移 · 拖动节点 · 点击查看详情</div></section>
  <section id="listview" class="view"></section>
  <div id="drawer"><span class="close" onclick="CloseDrawer()">×</span><div id="drawerbody"></div></div>
  <div id="pdfmodal"><div class="bar"><span class="name" id="pdfname"></span><a class="btn ghost" id="pdfnewtab" target="_blank">在新标签打开 ↗</a><span class="x" onclick="ClosePdf()">×</span></div><iframe id="pdfframe"></iframe></div>
  <div id="setmodal"><div class="setbox setbox-flex" style="width:min(560px,92vw)">
    <div class="setbox-head">
      <h2>⚙ 设置 · 大模型 API</h2>
      <p class="note">填写后，点「分析」即可自动把文献摄入知识库。兼容 OpenAI 接口（OpenAI / DeepSeek / 通义 / Moonshot 等）。Key 仅保存在本机 <code>.paper-helper/config.json</code>，不会上传。</p>
    </div>
    <div class="setbox-body">
      <label>快速选择（免费模型）</label>
      <select id="set_preset" onchange="ApplyPreset()"></select>
      <p class="note" id="preset_hint" style="margin:4px 0 0"></p>
      <label>API 地址（Base URL）</label>
      <input id="set_baseurl" placeholder="https://api.openai.com/v1">
      <label>API Key</label>
      <input id="set_apikey" type="password" placeholder="sk-...">
      <label>模型名称</label>
      <input id="set_model" placeholder="gpt-4o-mini">
      <label>输出语言</label>
      <select id="set_lang"><option value="中文">中文</option><option value="English">English</option></select>
    </div>
    <div class="setbox-foot"><button class="btn ghost" onclick="CloseSettings()">取消</button><button class="btn" onclick="SaveSettings()">保存</button></div>
  </div></div>
  <div id="topicmodal"><div class="setbox setbox-flex" style="width:min(600px,94vw)">
    <div class="setbox-head">
      <h2>＋ 新建选题</h2>
      <p class="note">选题以论文题目命名。可从下方选择历史题目一键导入；未导入时结构规则与工作规范沿用当前选题。</p>
      <div class="refbar">
        <span class="note" style="margin:0">从旧选题导入</span>
        <div class="refpick">
          <select id="newtopic_hist" class="refselect"></select>
          <button class="btn ghost" onclick="ImportTopicConfig('new')">一键导入</button>
        </div>
      </div>
    </div>
    <div class="setbox-body">
      <div class="purposeform" id="newtopic_form"></div>
    </div>
    <div class="setbox-foot"><button class="btn ghost" onclick="CloseNewTopic()">取消</button><button class="btn" onclick="CreateTopic()">创建并切换</button></div>
  </div></div>
  <div id="rulesmodal"><div class="setbox setbox-flex">
    <div class="setbox-head">
      <h2>📋 研究规则</h2>
      <p class="note">编辑当前选题的研究目标、结构规则与工作规范。研究目标默认显示当前内容；也可从历史选题一键导入。</p>
      <div class="ruletabs">
        <div class="ruletab active" data-rule="purpose" onclick="SwitchRuleTab('purpose')">研究目标</div>
        <div class="ruletab" data-rule="schema" onclick="SwitchRuleTab('schema')">结构规则</div>
        <div class="ruletab" data-rule="agents" onclick="SwitchRuleTab('agents')">工作规范</div>
      </div>
    </div>
    <div class="setbox-body">
      <div id="rule_purpose_panel" class="rule-panel active">
        <div class="refbar">
          <span class="note" style="margin:0">从旧选题导入</span>
          <div class="refpick">
            <select id="rule_hist" class="refselect"></select>
            <button class="btn ghost" onclick="ImportTopicConfig('rules')">一键导入</button>
          </div>
        </div>
        <div class="purposeform" id="rule_purpose_form"></div>
      </div>
      <div id="rule_schema_panel" class="rule-panel"><textarea class="ruleseditor" id="rule_schema_editor"></textarea></div>
      <div id="rule_agents_panel" class="rule-panel"><textarea class="ruleseditor" id="rule_agents_editor"></textarea></div>
    </div>
    <div class="setbox-foot"><button class="btn ghost" onclick="CloseRules()">取消</button><button class="btn" onclick="SaveRules()">保存</button></div>
  </div></div>
  <div id="querymodal"><div class="setbox" style="width:min(640px,94vw)">
    <h2>💬 知识库查询</h2>
    <p class="note">基于已编译 wiki 页面作答，结果可沉淀到 wiki/queries/。</p>
    <label>你的问题</label>
    <textarea id="query_input" style="min-height:88px;width:100%;padding:10px;border-radius:8px;border:1px solid var(--border);background:var(--panel2);color:var(--text);font-family:inherit;box-sizing:border-box" placeholder="例如：行政超载与政策分诊的因果证据有哪些？"></textarea>
    <div id="query_result" class="queryans" style="display:none;margin-top:12px"></div>
    <div class="row"><button class="btn ghost" onclick="CloseQuery()">关闭</button><button class="btn" onclick="SubmitQuery()">提问</button></div>
  </div></div>
  <div id="lintmodal"><div class="setbox" style="width:min(640px,94vw);max-height:88vh;overflow:auto">
    <h2>🩺 知识库巡检</h2>
    <div id="lint_body" class="lintlist">加载中…</div>
    <div class="row"><button class="btn ghost" onclick="CloseLint()">关闭</button><button class="btn" onclick="RunLint()">重新巡检</button></div>
  </div></div>
  <div id="startmodal"><div class="setbox">
    <h2>启动本地服务</h2>
    <p class="note">出于浏览器安全限制，网页无法直接启动本机程序。请用以下任一方式开启服务，开启后「添加 / 分析 / 刷新」即可使用：</p>
    <p style="font-size:13px;line-height:2">① 双击项目根目录的 <b>start.command</b><br>② 或复制下面命令到「终端」运行：</p>
    <input id="startcmdbox" readonly onclick="this.select()">
    <div class="row"><button class="btn ghost" onclick="CloseStart()">关闭</button><button class="btn" onclick="CopyStart()">复制命令</button></div>
  </div></div>
  <div id="overlay"><div class="spinner"></div><div class="msg" id="overlaymsg">处理中…</div><div id="progwrap"><div id="progbar"></div></div><div id="progtext"></div><div id="progfail" style="font-size:12px;color:#de5f7a;max-width:70vw;text-align:center;display:none"></div><button class="btn ghost cancelbtn" id="ingest_cancel_btn" style="display:none" onclick="CancelIngest()">取消分析</button></div>
</main>
<div id="toast"></div>
<script>
const SERVERMODE = /*__SERVERMODE__*/;
const DESKTOPMODE = /*__DESKTOPMODE__*/;
let DATA = /*__DATA__*/;
let TC = DATA.typeconfig;
let NODEMAP = {};
function ReindexNodes(){NODEMAP={};DATA.nodes.forEach(n=>NODEMAP[n.id]=n)}
ReindexNodes();

function TypeLabel(t){return (TC[t]||TC.unknown).label}
function TypeColor(t){return (TC[t]||TC.unknown).color}
function Esc(s){return (s||"").replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}
function Attr(s){return (s||"").replace(/'/g,"\\'").replace(/"/g,"&quot;")}
function SafeUrl(u){return(u||"").trim().match(/^https?:\/\//i)?u.trim():""}

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
    const pdfbtn=IsPdf(n.rawfile)?`<button class="pdfbtn" onclick="event.stopPropagation();OpenPdf('${Attr(n.rawfile)}')">${DESKTOPMODE?"📄 浏览器打开":"📄 打开 PDF"}</button>`:"";
    const surl=SafeUrl(n.url);
    const urlbtn=surl?`<button class="urlbtn" onclick="event.stopPropagation();OpenPaperUrl('${Attr(surl)}')">🔗 在线阅读</button>`:"";
    const del=(SERVERMODE&&n.rawfile)?`<span class="del" title="删除" onclick="event.stopPropagation();DeletePaper('${Attr(n.rawfile)}')">🗑</span>`:"";
    return `<div class="card ${n.ingested?'':'pending'}" onclick="OpenDrawer('${Attr(n.id)}')">
      ${del}<div class="ttl">${Esc(n.title)}</div>
      <div class="sub">${Esc(sub)||"—"}</div>
      <div class="sum">${Esc(n.summary||"")}</div>
      <div class="tags">${tags}</div>${urlbtn}${pdfbtn}</div>`;
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
  UpdateCurrentTopicDisplay();
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
  if(n.type==="source"){
    const surl=SafeUrl(n.url);
    if(surl)h+=`<div class="field"><button class="btn ghost" onclick="OpenPaperUrl('${Attr(surl)}')">🔗 在线阅读 ↗</button></div>`;
    if(SERVERMODE)h+=`<div class="field"><div class="k">论文网址</div><div class="urledit"><input id="paper_url_input" value="${Esc(n.url||"")}" placeholder="https://doi.org/... 或期刊页面"><button class="btn ghost" onclick="SavePaperUrl('${Attr(n.id)}','${Attr(n.rawfile||"")}')">保存</button></div></div>`;
  }
  if(n.summary)h+=`<div class="field"><div class="k">摘要</div>${Esc(n.summary)}</div>`;
  if((n.tags||[]).length)h+=`<div class="field"><div class="k">标签</div>${n.tags.map(t=>`<span class="badge soft">${Esc(t)}</span>`).join("")}</div>`;
  if(neigh.length)h+=`<div class="field links"><div class="k">关联页面 (${neigh.length})</div>${neigh.map(x=>`<a onclick="OpenDrawer('${Attr(x)}')">${Esc((NODEMAP[x]||{}).title||x)}</a>`).join("")}</div>`;
  if(!n.ingested&&n.rawfile)h+=`<div class="field"><button class="btn" onclick="Analyze('${Attr(n.rawfile)}')">✨ 分析这篇文献</button></div>`;
  document.getElementById("drawerbody").innerHTML=h;
  document.getElementById("drawer").classList.add("open");
}
function CloseDrawer(){document.getElementById("drawer").classList.remove("open")}
async function OpenPaperUrl(surl){
  surl=SafeUrl(surl);
  if(!surl){Toast("链接无效");return}
  if(DESKTOPMODE){
    try{await Api("/api/open/url",{url:surl});Toast("已在浏览器中打开")}
    catch(e){Toast("打开失败："+e.message)}
    return;
  }
  window.open(surl,"_blank","noopener");
}
async function SavePaperUrl(sid,sraw){
  if(NeedServer())return;
  const surl=document.getElementById("paper_url_input").value.trim();
  try{
    await Api("/api/source/url",{id:sid,rawfile:sraw||null,url:surl});
    const n=NODEMAP[sid];
    if(n)n.url=surl;
    DATA.nodes.filter(x=>x.id===sid).forEach(x=>{x.url=surl});
    RenderLibrary();
    OpenDrawer(sid);
    Toast(surl?"链接已保存":"链接已清除");
  }catch(e){Toast("保存失败："+e.message)}
}

/* ---------- PDF 预览 ---------- */
function IsPdf(f){return f&&/\.pdf$/i.test(f)}
function PdfHref(f){return "raw/sources/"+encodeURIComponent(f)}
async function OpenPdf(f){
  const href=PdfHref(f);
  if(DESKTOPMODE){
    try{await Api("/api/open/pdf",{rawfile:f});Toast("已在浏览器中打开 PDF")}
    catch(e){Toast("打开 PDF 失败："+e.message)}
    return;
  }
  document.getElementById("pdfname").textContent=f;
  document.getElementById("pdfframe").src=href;
  document.getElementById("pdfnewtab").href=href;
  document.getElementById("pdfmodal").classList.add("open");
}
function ClosePdf(){document.getElementById("pdfmodal").classList.remove("open");document.getElementById("pdfframe").src=""}
document.addEventListener("keydown",e=>{if(e.key==="Escape"){CloseTopicMenu();ClosePdf();CloseDrawer();CloseSettings();CloseStart();CloseRules();CloseNewTopic();CloseQuery();CloseLint()}});
document.addEventListener("click",e=>{const pick=document.getElementById("topic_pick");if(pick&&!pick.contains(e.target))CloseTopicMenu()});

/* ---------- 选题管理 ---------- */
const INIT_TOPICS=/*__INIT_TOPICS__*/;
let TOPICS=INIT_TOPICS.topics||[],CURRENT_TOPIC=INIT_TOPICS.current||"",PURPOSE_FIELDS=INIT_TOPICS.purpose_fields||[],RULES_CACHE={},ACTIVE_RULE_TAB="purpose",NEW_TOPIC_IMPORT_FROM="";
function TopicLabel(t){if(!t)return"";return (t.working_title||t.name||t.id||"").trim()}
function ApplyCurrentTopic(nid,sdisplay){
  CURRENT_TOPIC=nid||"";
  let cur=TOPICS.find(t=>t.id===CURRENT_TOPIC);
  if(cur&&sdisplay){cur.name=sdisplay;cur.working_title=sdisplay}
  else if(!cur&&sdisplay){TOPICS.unshift({id:CURRENT_TOPIC,name:sdisplay,working_title:sdisplay,current:true})}
  TOPICS.forEach(t=>{t.current=t.id===CURRENT_TOPIC});
  RenderTopicSelect();
  UpdateTopicPickBtn();
  UpdateCurrentTopicDisplay();
}
function UpdateCurrentTopicDisplay(){
  const el=document.getElementById("curtopic_title");
  const box=document.getElementById("curtopic");
  if(!el||!box)return;
  if(!SERVERMODE){box.style.display="none";return;}
  box.style.display="";
  const cur=TOPICS.find(t=>t.id===CURRENT_TOPIC);
  const stitle=cur?TopicLabel(cur):"未选择选题";
  el.textContent=stitle;
  el.title=stitle;
}
const TOPIC_HOVER_MS=500;
function UpdateTopicPickBtn(){
  const lbl=document.getElementById("topic_pick_lbl");
  if(!lbl)return;
  const cur=TOPICS.find(t=>t.id===CURRENT_TOPIC);
  const stitle=cur?TopicLabel(cur):"未选择选题";
  lbl.textContent=stitle;
  lbl.title=stitle;
}
function ResetTopicItemScroll(el){
  if(!el)return;
  clearTimeout(el._hoverTimer);
  const text=el.querySelector(".topicpick-text");
  if(text){text.style.transition="";text.style.transform=""}
}
function StartTopicItemScroll(el){
  const text=el.querySelector(".topicpick-text");
  if(!text)return;
  const cs=getComputedStyle(el);
  const npad=parseFloat(cs.paddingLeft)+parseFloat(cs.paddingRight);
  const nview=el.clientWidth-npad;
  const ntext=Math.max(text.scrollWidth,Math.ceil(text.getBoundingClientRect().width));
  const nbuffer=14;
  const ndist=ntext-nview+nbuffer;
  if(ndist<=0)return;
  const ndur=Math.max(1.8,ndist/36);
  text.style.transition=`transform ${ndur}s linear`;
  text.style.transform=`translateX(-${ndist}px)`;
}
function BindTopicPickItem(el){
  el.addEventListener("mouseenter",()=>{
    ResetTopicItemScroll(el);
    el._hoverTimer=setTimeout(()=>{if(el.matches(":hover"))StartTopicItemScroll(el)},TOPIC_HOVER_MS);
  });
  el.addEventListener("mouseleave",()=>ResetTopicItemScroll(el));
}
function CloseTopicMenu(){
  const pick=document.getElementById("topic_pick");
  if(!pick)return;
  pick.classList.remove("open");
  pick.querySelectorAll(".topicpick-item").forEach(ResetTopicItemScroll);
}
function ToggleTopicMenu(e){
  e.stopPropagation();
  const pick=document.getElementById("topic_pick");
  if(!pick)return;
  pick.classList.toggle("open");
}
function RenderTopicSelect(){
  const menu=document.getElementById("topic_pick_menu");
  if(!menu)return;
  menu.innerHTML=TOPICS.map(t=>{
    const slabel=TopicLabel(t);
    return `<div class="topicpick-item${t.id===CURRENT_TOPIC?" active":""}" data-id="${Attr(t.id)}" title="${Esc(slabel)}"><span class="topicpick-text">${Esc(slabel)}</span></div>`;
  }).join("");
  menu.querySelectorAll(".topicpick-item").forEach(el=>{
    BindTopicPickItem(el);
    el.onclick=e=>{e.stopPropagation();PickTopic(el.dataset.id)};
  });
  UpdateTopicPickBtn();
}
async function PickTopic(nid){
  CloseTopicMenu();
  if(!nid||nid===CURRENT_TOPIC)return;
  ShowOverlay("正在切换选题…");
  try{
    const result=await Api("/api/topics/switch",{id:nid});
    ApplyCurrentTopic(result.id||nid,result.name);
    await Refresh(true);
    await LoadTopics();
    HideOverlay();Toast("已切换选题");
  }catch(e){HideOverlay();Toast("切换失败："+e.message)}
}
function PopulateHistoryDropdown(sselid,bexcludecurrent){
  const sel=document.getElementById(sselid);
  if(!sel)return;
  const vhist=TOPICS.filter(t=>!bexcludecurrent||t.id!==CURRENT_TOPIC);
  if(!vhist.length){sel.innerHTML='<option value="">（暂无历史选题）</option>';return;}
  sel.innerHTML='<option value="">选择历史论文题目…</option>'+vhist.map(t=>{
    const slabel=TopicLabel(t);
    return `<option value="${Attr(t.id)}">${Esc(slabel)}</option>`;
  }).join("");
}
async function ImportTopicConfig(smode){
  const sselid=smode==="new"?"newtopic_hist":"rule_hist";
  const sformid=smode==="new"?"newtopic_form":"rule_purpose_form";
  const nid=document.getElementById(sselid).value;
  if(!nid){Toast("请先选择历史论文题目");return;}
  try{
    const cfg=await Api("/api/topics/config?id="+encodeURIComponent(nid));
    BuildPurposeForm(sformid,cfg.fields||{});
    if(smode==="new"){
      NEW_TOPIC_IMPORT_FROM=nid;
      Toast("已导入研究目标；创建时将同步导入结构规则与工作规范");
    }else{
      document.getElementById("rule_schema_editor").value=cfg.schema||"";
      document.getElementById("rule_agents_editor").value=cfg.agents||"";
      Toast("已导入该选题的完整配置");
    }
  }catch(e){Toast("导入失败："+e.message)}
}
function BuildPurposeForm(scontainerid,ofields){
  const box=document.getElementById(scontainerid);
  if(!box)return;
  box.innerHTML=PURPOSE_FIELDS.map(f=>{
    const v=Esc((ofields&&ofields[f.key])||"");
    const ta=f.key==="thesis"||f.key==="outline"||f.key==="milestones";
    const stag=f.required?'<span class="reqtag">*</span><span class="opttag">必填</span>':'<span class="opttag">选填</span>';
    const ph=f.required?"必填":"选填，可留空";
    return `<label>${Esc(f.label)}${stag}</label>${ta?`<textarea data-k="${f.key}" placeholder="${ph}">${v}</textarea>`:`<input data-k="${f.key}" value="${v}" placeholder="${ph}">`}`;
  }).join("");
}
function ValidatePurposeForm(scontainerid){
  const o=ReadPurposeForm(scontainerid);
  if(!o.working_title){Toast("请填写论文题目");return false;}
  return true;
}
function ReadPurposeForm(scontainerid){
  const o={};document.querySelectorAll("#"+scontainerid+" [data-k]").forEach(el=>{o[el.dataset.k]=el.value.trim()});return o;
}
async function LoadTopics(){
  if(!SERVERMODE)return;
  try{
    const r=await Api("/api/topics");
    TOPICS=r.topics||[];CURRENT_TOPIC=r.current||"";PURPOSE_FIELDS=r.purpose_fields||PURPOSE_FIELDS;
    RenderTopicSelect();UpdateTopicPickBtn();
    document.getElementById("metainfo").textContent=(SERVERMODE?"本地服务 · ":"")+"更新于 "+DATA.generated;
    UpdateCurrentTopicDisplay();
  }catch(e){console.error("LoadTopics",e)}
}
async function SwitchTopic(nid){return PickTopic(nid||CURRENT_TOPIC)}
async function OpenNewTopic(){
  if(NeedServer())return;
  NEW_TOPIC_IMPORT_FROM="";
  if(!TOPICS.length)await LoadTopics();
  PopulateHistoryDropdown("newtopic_hist",false);
  BuildPurposeForm("newtopic_form",{});
  document.getElementById("topicmodal").classList.add("open");
}
function CloseNewTopic(){document.getElementById("topicmodal").classList.remove("open");NEW_TOPIC_IMPORT_FROM=""}
async function CreateTopic(){
  if(NeedServer())return;
  if(!ValidatePurposeForm("newtopic_form"))return;
  const ofields=ReadPurposeForm("newtopic_form");
  ShowOverlay("正在创建选题…");
  try{
    const obody={name:ofields.working_title,fields:ofields};
    if(NEW_TOPIC_IMPORT_FROM)obody.import_from=NEW_TOPIC_IMPORT_FROM;
    const result=await Api("/api/topics/new",obody);
    ApplyCurrentTopic(result.id,result.name||ofields.working_title);
    CloseNewTopic();await Refresh(true);await LoadTopics();HideOverlay();Toast("新选题已创建");
  }catch(e){HideOverlay();Toast("创建失败："+e.message)}
}
async function ResetTopic(){
  if(NeedServer())return;
  if(!confirm("确定重置当前选题？\n\n将清空已添加的文献与全部分析页面，研究目标恢复范本；结构规则与工作规范保留不变。"))return;
  ShowOverlay("正在重置…");
  try{
    await Api("/api/topics/reset",{});
    await Refresh(true);await LoadTopics();HideOverlay();Toast("当前选题已重置");
  }catch(e){HideOverlay();Toast("重置失败："+e.message)}
}
async function OpenRules(){
  if(NeedServer())return;
  try{
    RULES_CACHE=await Api("/api/rules");
    if(!TOPICS.length)await LoadTopics();
    PopulateHistoryDropdown("rule_hist",true);
    BuildPurposeForm("rule_purpose_form",(RULES_CACHE.purpose&&RULES_CACHE.purpose.fields)||{});
    document.getElementById("rule_schema_editor").value=(RULES_CACHE.schema&&RULES_CACHE.schema.content)||"";
    document.getElementById("rule_agents_editor").value=(RULES_CACHE.agents&&RULES_CACHE.agents.content)||"";
    SwitchRuleTab("purpose");
    document.getElementById("rulesmodal").classList.add("open");
  }catch(e){Toast("加载规则失败："+e.message)}
}
function CloseRules(){document.getElementById("rulesmodal").classList.remove("open")}
function SwitchRuleTab(stab){
  ACTIVE_RULE_TAB=stab;
  document.querySelectorAll(".ruletab").forEach(t=>t.classList.toggle("active",t.dataset.rule===stab));
  ["purpose","schema","agents"].forEach(k=>{
    document.getElementById("rule_"+k+"_panel").classList.toggle("active",k===stab);
  });
}
async function SaveRules(){
  if(NeedServer())return;
  try{
    if(ACTIVE_RULE_TAB==="purpose"){
      if(!ValidatePurposeForm("rule_purpose_form"))return;
      await Api("/api/rules/save",{key:"purpose",fields:ReadPurposeForm("rule_purpose_form")});
    }else if(ACTIVE_RULE_TAB==="schema"){
      await Api("/api/rules/save",{key:"schema",content:document.getElementById("rule_schema_editor").value});
    }else{
      await Api("/api/rules/save",{key:"agents",content:document.getElementById("rule_agents_editor").value});
    }
    CloseRules();
    await LoadTopics();
    Toast("规则已保存");
  }catch(e){Toast("保存失败："+e.message)}
}

/* ---------- 服务开关 ---------- */
const STARTCMD="/*__STARTCMD__*/";
let serverUp=SERVERMODE;
function InitSvcToggle(){
  const t=document.getElementById("svctoggle");
  t.checked=serverUp;
  document.getElementById("svclbl").textContent=serverUp?"运行中":"已停止";
  t.onchange=()=>{
    if(DESKTOPMODE){
      if(t.checked){serverUp=true;document.getElementById("svclbl").textContent="运行中";Toast("功能已开启");}
      else{
        if(!confirm("确定暂停导入/分析功能？\n暂停后添加、分析、删除将不可用，打开开关即可恢复。")){t.checked=true;return;}
        serverUp=false;document.getElementById("svclbl").textContent="已暂停";Toast("功能已暂停");
      }
      return;
    }
    if(serverUp){t.checked=true;StopService();}
    else{t.checked=false;OpenStart();}
  };
}
async function StopService(){
  if(!confirm("确定停止本地服务？\n停止后将无法添加/分析。"))return;
  try{await Api("/api/shutdown",{});}catch(e){}
  serverUp=false;
  document.getElementById("svctoggle").checked=false;
  document.getElementById("svclbl").textContent="已停止";
  document.getElementById("toolbar").innerHTML='<span class="meta">📖 服务已停止 · 请重新启动应用</span>';
  Toast("服务已停止");
}
function OpenStart(){document.getElementById("startcmdbox").value='bash "'+STARTCMD+'"';document.getElementById("startmodal").classList.add("open")}
function CloseStart(){document.getElementById("startmodal").classList.remove("open")}
function CopyStart(){const b=document.getElementById("startcmdbox");b.select();try{document.execCommand("copy")}catch(e){}if(navigator.clipboard)navigator.clipboard.writeText(b.value).catch(()=>{});Toast("已复制启动命令")}

/* ---------- 工具栏动作 ---------- */
function Toast(msg,ms){const t=document.getElementById("toast");t.textContent=msg;t.classList.add("show");clearTimeout(t._t);t._t=setTimeout(()=>t.classList.remove("show"),ms||3000)}
function ShowOverlay(msg){document.getElementById("overlaymsg").textContent=msg||"处理中…";document.getElementById("overlay").classList.add("open")}
function HideOverlay(){document.getElementById("overlay").classList.remove("open")}
function NeedServer(){
  if(DESKTOPMODE&&!serverUp){Toast("功能已暂停，请打开右上角服务开关");return true}
  if(!SERVERMODE){Toast("此功能需启动 Paper-Helper 应用后使用");return true}
  return false;
}

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
async function UploadFiles(vfiles){
  if(!vfiles.length)return;
  ShowOverlay(`正在上传 ${vfiles.length} 个文件…`);
  try{
    for(const f of vfiles){const b64=await FileToBase64(f);await Api("/api/upload",{name:f.name,data:b64})}
    await Refresh(true);HideOverlay();Toast(`已添加 ${vfiles.length} 篇文献`);
  }catch(e){HideOverlay();Toast("上传失败："+e.message)}
}
function InitDropzone(){
  const dz=document.getElementById("dropzone");if(!dz||!SERVERMODE)return;
  ["dragenter","dragover"].forEach(ev=>dz.addEventListener(ev,e=>{e.preventDefault();dz.classList.add("drag")}));
  ["dragleave","drop"].forEach(ev=>dz.addEventListener(ev,e=>{e.preventDefault();dz.classList.remove("drag")}));
  dz.addEventListener("drop",e=>{if(NeedServer())return;UploadFiles([...e.dataTransfer.files])});
}
function OpenQuery(){if(NeedServer())return;document.getElementById("query_result").style.display="none";document.getElementById("querymodal").classList.add("open")}
function CloseQuery(){document.getElementById("querymodal").classList.remove("open")}
async function SubmitQuery(){
  if(NeedServer())return;
  const sq=document.getElementById("query_input").value.trim();
  if(!sq){Toast("请输入问题");return}
  ShowOverlay("正在查询…");
  try{
    const r=await Api("/api/query",{question:sq,save:true});
    HideOverlay();
    if(r.status==="need_key"){Toast("请先配置 API Key");OpenSettings();return}
    const box=document.getElementById("query_result");
    box.style.display="block";box.textContent=r.answer||"";
    if(r.saved)Toast("已保存至 wiki/queries/"+r.saved.id);
    await Refresh(true);
  }catch(e){HideOverlay();Toast("查询失败："+e.message)}
}
function CloseLint(){document.getElementById("lintmodal").classList.remove("open")}
function RenderLintReport(r){
  let h="<ul>";
  h+="<li>孤立页面："+(r.orphans?r.orphans.length:0);
  if(r.orphans&&r.orphans.length)h+=" — "+r.orphans.slice(0,8).map(x=>Esc(x.id)).join(", ");
  h+="</li><li>死链："+(r.dead_links?r.dead_links.length:0);
  if(r.dead_links&&r.dead_links.length)h+="<br>"+r.dead_links.slice(0,6).map(x=>Esc(x.page)+"→"+Esc(x.link)).join("<br>");
  h+="</li><li>frontmatter 问题："+(r.frontmatter_issues?r.frontmatter_issues.length:0)+"</li>";
  h+="<li>知识空白："+(r.knowledge_gaps?r.knowledge_gaps.length:0)+"</li></ul>";
  document.getElementById("lint_body").innerHTML=h;
}
async function RunLint(){
  if(NeedServer())return;
  document.getElementById("lintmodal").classList.add("open");
  document.getElementById("lint_body").textContent="巡检中…";
  try{const r=await Api("/api/lint");RenderLintReport(r)}catch(e){document.getElementById("lint_body").textContent="失败："+e.message}
}
async function ExportBib(){
  if(NeedServer())return;
  try{
    const r=await Api("/api/export/bibtex");
    const blob=new Blob([r.bibtex||""],{type:"text/plain"});
    const a=document.createElement("a");a.href=URL.createObjectURL(blob);a.download="sources.bib";a.click();
    Toast("BibTeX 已导出");
  }catch(e){Toast("导出失败："+e.message)}
}
async function SnapshotTopic(){
  if(NeedServer())return;
  try{const r=await Api("/api/topics/snapshot",{});Toast("已备份至 "+r.path,5000)}catch(e){Toast("备份失败："+e.message)}
}

async function DeletePaper(rawfile){
  if(NeedServer())return;
  if(!confirm("确定删除该文献？\n"+rawfile))return;
  const bcascade=confirm("是否同时删除关联知识页？\n\n确定 = 删除 sources 含该文献的页面\n取消 = 仅删 PDF 与 source 摘要页");
  ShowOverlay("正在删除…");
  try{const r=await Api("/api/delete",{rawfile,cascade:bcascade});await Refresh(true);HideOverlay();Toast("已删除 "+(r.removed?r.removed.length:0)+" 项")}
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
  document.getElementById("progfail").style.display="none";
  document.getElementById("ingest_cancel_btn").style.display="";
}
async function CancelIngest(){
  try{await Api("/api/ingest/cancel",{});Toast("正在取消…")}catch(e){Toast("取消失败："+e.message)}
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
  document.getElementById("ingest_cancel_btn").style.display="none";
  const pf=document.getElementById("progfail");
  if(p&&p.failed&&p.failed.length){
    pf.style.display="block";
    pf.innerHTML=p.failed.map(x=>Esc(x.file)+": "+Esc(x.error)).join("<br>");
  }else{pf.style.display="none"}
  HideOverlay();
  Refresh(true);CloseDrawer();
  if(p){let msg=`完成：成功 ${p.ingested?p.ingested.length:0} 篇`;if(p.failed&&p.failed.length)msg+=`，失败 ${p.failed.length} 篇`;if(p.cancelled)msg+="（已取消）";Toast(msg,6000)}
}

/* ---------- 设置 ---------- */
/* 内置免费模型预设：均为 OpenAI 兼容接口，模型本身免费，Key 需自行免费申请 */
const PRESETS=[
  {name:"⚡ Pollinations（免注册·直接可用）",base_url:"https://text.pollinations.ai/openai",model:"openai",noauth:true,hint:"公共代理端点，无需注册/无需 Key。但有较强限流、且为开源推理模型，可能不稳定或分析失败；正式使用建议改用下方带 Key 的免费模型（注册约 1 分钟）。"},
  {name:"OpenRouter · DeepSeek V3（免费）",base_url:"https://openrouter.ai/api/v1",model:"deepseek/deepseek-chat-v3-0324:free",hint:"免费注册获取 Key（sk-or-...）",reg_url:"https://openrouter.ai/keys"},
  {name:"OpenRouter · Gemini 2.0 Flash（免费）",base_url:"https://openrouter.ai/api/v1",model:"google/gemini-2.0-flash-exp:free",hint:"免费注册获取 Key（sk-or-...）",reg_url:"https://openrouter.ai/keys"},
  {name:"OpenRouter · Llama 3.3 70B（免费）",base_url:"https://openrouter.ai/api/v1",model:"meta-llama/llama-3.3-70b-instruct:free",hint:"免费注册获取 Key（sk-or-...）",reg_url:"https://openrouter.ai/keys"},
  {name:"智谱 GLM-4-Flash（免费）",base_url:"https://open.bigmodel.cn/api/paas/v4",model:"glm-4-flash",hint:"免费注册获取 API Key",reg_url:"https://open.bigmodel.cn/usercenter/apikeys"},
  {name:"Groq · Llama 3.3 70B（免费额度）",base_url:"https://api.groq.com/openai/v1",model:"llama-3.3-70b-versatile",hint:"免费注册获取 Key（gsk_...）",reg_url:"https://console.groq.com/keys"},
];
function BuildPresetOptions(){
  const sel=document.getElementById("set_preset");
  sel.innerHTML=`<option value="">— 自定义 —</option>`+PRESETS.map((p,i)=>`<option value="${i}">${p.name}</option>`).join("");
}
function ApplyPreset(){
  const i=document.getElementById("set_preset").value;
  const hint=document.getElementById("preset_hint");
  if(i===""){hint.innerHTML="";return}
  const p=PRESETS[+i];
  document.getElementById("set_baseurl").value=p.base_url;
  document.getElementById("set_model").value=p.model;
  if(p.noauth){
    document.getElementById("set_apikey").value="";
    hint.innerHTML="✅ "+p.hint;
  }else{
    hint.innerHTML="提示："+p.hint+`　👉 <a href="${p.reg_url}" target="_blank" rel="noopener">点此免费注册 ↗</a>`;
  }
}
async function OpenSettings(){
  if(NeedServer())return;
  BuildPresetOptions();
  try{const c=await Api("/api/config");
    document.getElementById("set_baseurl").value=c.base_url||"https://api.openai.com/v1";
    document.getElementById("set_apikey").value=c.api_key||"";
    document.getElementById("set_model").value=c.model||"gpt-4o-mini";
    document.getElementById("set_lang").value=c.language||"中文";
    const idx=PRESETS.findIndex(p=>p.base_url===c.base_url&&p.model===c.model);
    document.getElementById("set_preset").value=idx>=0?String(idx):"";
    ApplyPreset();
  }catch(e){}
  document.getElementById("setmodal").classList.add("open");
}
function CloseSettings(){document.getElementById("setmodal").classList.remove("open")}
async function SaveSettings(){
  const body={base_url:document.getElementById("set_baseurl").value.trim(),api_key:document.getElementById("set_apikey").value.trim(),model:document.getElementById("set_model").value.trim(),language:document.getElementById("set_lang").value};
  try{await Api("/api/config",body);CloseSettings();Toast("设置已保存")}catch(e){Toast("保存失败："+e.message)}
}

/* ---------- 力导向知识图谱 ---------- */
let canvas,ctx,nodes=[],links=[],view={x:0,y:0,scale:1},dragnode=null,dragging=false,last={x:0,y:0},hover=null,rafid=null,GRAPH_FILTER="";
function BuildGraphFilter(){
  const sel=document.getElementById("graph_filter");if(!sel)return;
  const vtypes=[...new Set(DATA.nodes.map(n=>n.type))];
  const vcur=sel.value;
  sel.innerHTML='<option value="">全部类型</option>'+vtypes.map(t=>`<option value="${t}">${TypeLabel(t)}</option>`).join("");
  if(vcur)sel.value=vcur;
}
function ApplyGraphFilter(){GRAPH_FILTER=document.getElementById("graph_filter").value;canvas=null;InitGraph()}
function InitGraph(){
  canvas=document.getElementById("graphcanvas");ctx=canvas.getContext("2d");ResizeCanvas();BuildGraphFilter();
  const w=canvas.clientWidth,hh=canvas.clientHeight;
  const vraw=GRAPH_FILTER?DATA.nodes.filter(n=>n.type===GRAPH_FILTER):DATA.nodes;
  const ncount=Math.max(vraw.length,1);
  nodes=vraw.map((n,i)=>({...n,x:w/2+Math.cos(i/ncount*6.28)*150+(Math.random()-.5)*40,y:hh/2+Math.sin(i/ncount*6.28)*150+(Math.random()-.5)*40,vx:0,vy:0,r:7+Math.min(n.degree*2.5,16)}));
  const nm={};nodes.forEach(n=>nm[n.id]=n);
  const vids=new Set(nodes.map(n=>n.id));
  links=DATA.edges.map(e=>({s:nm[e.source],t:nm[e.target]})).filter(l=>l.s&&l.t&&vids.has(l.s.id)&&vids.has(l.t.id));
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

if(!SERVERMODE){
  document.getElementById("toolbar").innerHTML='<span class="meta">📖 只读模式 · 请打开 <b>Paper-Helper</b> 应用以添加/分析文献</span>';
  const tb=document.getElementById("topicbar");if(tb)tb.style.display="none";
  UpdateCurrentTopicDisplay();
}else{
  RenderTopicSelect();
  UpdateCurrentTopicDisplay();
}
InitSvcToggle();
InitDropzone();
RenderAll();
if(SERVERMODE){LoadTopics().then(()=>Refresh(true));}
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
