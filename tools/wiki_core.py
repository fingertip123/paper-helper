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
import doc_editor as docs  # noqa: E402

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
    docs.Init(topics.GetTopicDir())


ReloadTopicPaths()

outputpath = os.path.join(rootdir, "wiki-viewer.html")

# 各页面类型的展示配置：标签 + 颜色 + 目录
typeconfig = {
    "source": {"label": "文献", "color": "#7eb8d4", "dir": "sources"},
    "concept": {"label": "概念", "color": "#e8b86d", "dir": "concepts"},
    "entity": {"label": "实体", "color": "#b89fd8", "dir": "entities"},
    "rq": {"label": "研究问题", "color": "#d4899f", "dir": "research-questions"},
    "experiment": {"label": "实验", "color": "#8ec9a8", "dir": "experiments"},
    "synthesis": {"label": "综合", "color": "#8ec4d4", "dir": "synthesis"},
    "comparison": {"label": "对比", "color": "#d4a87a", "dir": "comparisons"},
    "query": {"label": "问答", "color": "#a8c47a", "dir": "queries"},
    "purpose": {"label": "目标", "color": "#d49a7a", "dir": ""},
    "unknown": {"label": "其他", "color": "#b0a4ad", "dir": ""},
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


def CountTopicSources(ntopicid):
    """统计指定选题下的文献数量（与论文库展示一致）。"""
    ntdir = topics.GetTopicDir(ntopicid)
    rdir = os.path.join(ntdir, "raw", "sources")
    wdir = os.path.join(ntdir, "wiki", "sources")
    vkeys = set()
    if os.path.isdir(rdir):
        for fn in os.listdir(rdir):
            if fn.lower().endswith((".pdf", ".docx", ".md", ".txt")) and not fn.startswith("."):
                vkeys.add(ParseSourceFilename(fn)["key"])
    if os.path.isdir(wdir):
        for fn in os.listdir(wdir):
            if fn.endswith(".md") and not fn.startswith("_"):
                vkeys.add(os.path.splitext(fn)[0])
    return len(vkeys)


def TopicsWithCounts():
    vtopics = topics.ListTopics()
    for t in vtopics:
        t["source_count"] = CountTopicSources(t["id"])
    return vtopics


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
            "topics": TopicsWithCounts(),
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
<script>try{document.documentElement.setAttribute("data-theme",localStorage.getItem("ph_theme")||"girly")}catch(e){}</script>
<style>
  :root{--radius:14px;--radius-sm:10px;--radius-lg:20px}
  :root,[data-theme="girly"]{--surface-hi:rgba(255,255,255,.48);--bg1:#faf6f4;--bg2:#f5ece8;--bg3:#f8f2f6;--panel:#fffcfb;--panel2:#f6f0ee;--panel-glass:rgba(255,252,251,.92);--float-panel:rgba(255,252,251,.88);--border:#eadfd9;--text:#4a3f47;--text-soft:#6d5f68;--muted:#9a8a94;--badge-text:#4a3f47;--accent:#c9789a;--accent2:#d9a0b8;--accent3:#b89fd8;--rose:#d4899f;--sage:#7eb89a;--gold:#e8b86d;--shadow:0 12px 40px rgba(74,63,71,.1);--shadow-sm:0 4px 16px rgba(74,63,71,.07);--btn-shadow:0 4px 14px rgba(201,120,154,.24);--tab-shadow:0 4px 12px rgba(201,120,154,.28);--card-hover-border:rgba(201,120,154,.45);--card-hover-shadow:0 14px 32px rgba(201,120,154,.14);--focus-border:rgba(201,120,154,.55);--focus-shadow:rgba(201,120,154,.12);--scroll-thumb:rgba(201,120,154,.28);--modal-backdrop:rgba(74,63,71,.32);--overlay-backdrop:rgba(74,63,71,.28);--dropzone-border:rgba(201,120,154,.35);--dropzone-drag:rgba(201,120,154,.08);--dropzone-bg:rgba(255,255,255,.45);--doc-preview-bg:#e8e2de;--revpick-bg:rgba(201,120,154,.08);--cmt-active-bg:rgba(201,120,154,.06);--cmt-active-border:rgba(201,120,154,.45);--ghost-hover:rgba(201,120,154,.08);--btn-sec-hover:rgba(201,120,154,.4);--ruletab-hover:rgba(201,120,154,.35);--svc-on-bg:rgba(201,120,154,.22);--toast-border:rgba(201,120,154,.35);--toast-shadow:0 10px 32px rgba(201,120,154,.18);--drawer-bg:rgba(255,252,251,.97);--drawer-shadow:-8px 0 32px rgba(74,63,71,.08);--revdiff-loading:rgba(255,252,251,.72);--graph-link:rgba(74,63,71,.14);--graph-link-active:rgba(201,120,154,.75);--graph-label:#4a3f47;--graph-ring:rgba(74,63,71,.35);  --tab-hover:rgba(255,255,255,.7);--depth3d:rgba(201,120,154,.1);--ambient3d:rgba(201,120,154,.06);--inset-edge3d:rgba(217,160,184,.09);--inset-press3d:rgba(201,120,154,.07);--rim3d:rgba(201,120,154,.18);--stone-fade3d:rgba(217,160,184,.22);--btn-depth3d:rgba(190,115,145,.13);--btn-ambient3d:rgba(201,120,154,.08);--btn-press3d:rgba(201,120,154,.09)}
  [data-theme="fresh"]{--surface-hi:rgba(255,255,255,.52);--bg1:#f3f5f2;--bg2:#eceee9;--bg3:#f0f2ef;--panel:#f8f9f7;--panel2:#eef1ec;--panel-glass:rgba(248,249,247,.94);--float-panel:rgba(248,249,247,.9);--border:#d8ddd4;--text:#3f4a44;--text-soft:#5a6560;--muted:#8a9490;--badge-text:#3f4a44;--accent:#7a9488;--accent2:#94a89e;--accent3:#a8b8a4;--rose:#b88888;--sage:#7a9488;--gold:#b8a878;--shadow:0 12px 40px rgba(63,74,68,.08);--shadow-sm:0 4px 16px rgba(63,74,68,.06);--btn-shadow:0 4px 14px rgba(122,148,136,.18);--tab-shadow:0 4px 12px rgba(122,148,136,.2);--card-hover-border:rgba(122,148,136,.38);--card-hover-shadow:0 14px 32px rgba(122,148,136,.1);--focus-border:rgba(122,148,136,.42);--focus-shadow:rgba(122,148,136,.1);--scroll-thumb:rgba(122,148,136,.24);--modal-backdrop:rgba(63,74,68,.22);--overlay-backdrop:rgba(63,74,68,.2);--dropzone-border:rgba(122,148,136,.28);--dropzone-drag:rgba(122,148,136,.07);--dropzone-bg:rgba(248,249,247,.65);--doc-preview-bg:#e6ebe6;--revpick-bg:rgba(122,148,136,.08);--cmt-active-bg:rgba(122,148,136,.06);--cmt-active-border:rgba(122,148,136,.32);--ghost-hover:rgba(122,148,136,.08);--btn-sec-hover:rgba(122,148,136,.35);--ruletab-hover:rgba(122,148,136,.3);--svc-on-bg:rgba(122,148,136,.16);--toast-border:rgba(122,148,136,.28);--toast-shadow:0 10px 32px rgba(122,148,136,.12);--drawer-bg:rgba(248,249,247,.97);--drawer-shadow:-8px 0 32px rgba(63,74,68,.06);--revdiff-loading:rgba(248,249,247,.8);--graph-link:rgba(63,74,68,.12);--graph-link-active:rgba(122,148,136,.62);--graph-label:#3f4a44;--graph-ring:rgba(63,74,68,.28);  --tab-hover:rgba(255,255,255,.55);--depth3d:rgba(122,148,136,.09);--ambient3d:rgba(122,148,136,.05);--inset-edge3d:rgba(148,168,158,.08);--inset-press3d:rgba(122,148,136,.06);--rim3d:rgba(122,148,136,.16);--stone-fade3d:rgba(148,168,158,.2);--btn-depth3d:rgba(106,138,124,.11);--btn-ambient3d:rgba(122,148,136,.07);--btn-press3d:rgba(122,148,136,.08)}
  [data-theme="boyish"]{--surface-hi:rgba(255,255,255,.55);--bg1:#f0f4fa;--bg2:#e8eef8;--bg3:#eef2fa;--panel:#ffffff;--panel2:#eef3fa;--panel-glass:rgba(255,255,255,.94);--float-panel:rgba(255,255,255,.9);--border:#c8d8ec;--text:#1e3a5f;--text-soft:#3d5a80;--muted:#6a85a8;--badge-text:#1e3a5f;--accent:#3d7dd6;--accent2:#5a9de8;--accent3:#f0a050;--rose:#e06070;--sage:#4aaa78;--gold:#e8a040;--shadow:0 12px 40px rgba(30,58,95,.1);--shadow-sm:0 4px 16px rgba(30,58,95,.08);--btn-shadow:0 4px 14px rgba(61,125,214,.28);--tab-shadow:0 4px 12px rgba(61,125,214,.26);--card-hover-border:rgba(61,125,214,.5);--card-hover-shadow:0 14px 32px rgba(61,125,214,.16);--focus-border:rgba(61,125,214,.55);--focus-shadow:rgba(61,125,214,.14);--scroll-thumb:rgba(61,125,214,.3);--modal-backdrop:rgba(30,58,95,.3);--overlay-backdrop:rgba(30,58,95,.26);--dropzone-border:rgba(61,125,214,.38);--dropzone-drag:rgba(61,125,214,.1);--dropzone-bg:rgba(255,255,255,.6);--doc-preview-bg:#d0d8e4;--revpick-bg:rgba(61,125,214,.1);--cmt-active-bg:rgba(61,125,214,.07);--cmt-active-border:rgba(61,125,214,.45);--ghost-hover:rgba(61,125,214,.08);--btn-sec-hover:rgba(61,125,214,.45);--ruletab-hover:rgba(61,125,214,.4);--svc-on-bg:rgba(61,125,214,.2);--toast-border:rgba(61,125,214,.38);--toast-shadow:0 10px 32px rgba(61,125,214,.18);--drawer-bg:rgba(255,255,255,.97);--drawer-shadow:-8px 0 32px rgba(30,58,95,.1);--revdiff-loading:rgba(255,255,255,.78);--graph-link:rgba(30,58,95,.14);--graph-link-active:rgba(61,125,214,.75);--graph-label:#1e3a5f;--graph-ring:rgba(30,58,95,.35);  --tab-hover:rgba(255,255,255,.8);--depth3d:rgba(61,125,214,.1);--ambient3d:rgba(61,125,214,.06);--inset-edge3d:rgba(140,175,220,.09);--inset-press3d:rgba(61,125,214,.07);--rim3d:rgba(61,125,214,.2);--stone-fade3d:rgba(140,175,220,.22);--btn-depth3d:rgba(50,110,195,.13);--btn-ambient3d:rgba(61,125,214,.08);--btn-press3d:rgba(61,125,214,.09)}
  [data-theme="cool"]{--surface-hi:rgba(255,255,255,.1);--bg1:#0d1117;--bg2:#121820;--bg3:#0f1419;--panel:#161b22;--panel2:#1c2330;--panel-glass:rgba(22,27,34,.94);--float-panel:rgba(22,27,34,.9);--border:#30363d;--text:#e6edf3;--text-soft:#b8c4d0;--muted:#7d8a98;--badge-text:#e6edf3;--accent:#00d4ff;--accent2:#a855f7;--accent3:#22d3ee;--rose:#ff6b8a;--sage:#34d399;--gold:#fbbf24;--shadow:0 12px 40px rgba(0,0,0,.45);--shadow-sm:0 4px 16px rgba(0,0,0,.32);--btn-shadow:0 4px 18px rgba(0,212,255,.22);--tab-shadow:0 4px 14px rgba(0,212,255,.28);--card-hover-border:rgba(0,212,255,.45);--card-hover-shadow:0 14px 36px rgba(0,212,255,.12);--focus-border:rgba(0,212,255,.55);--focus-shadow:rgba(0,212,255,.16);--scroll-thumb:rgba(0,212,255,.28);--modal-backdrop:rgba(0,0,0,.55);--overlay-backdrop:rgba(0,0,0,.48);--dropzone-border:rgba(0,212,255,.32);--dropzone-drag:rgba(0,212,255,.08);--dropzone-bg:rgba(28,35,48,.55);--doc-preview-bg:#2a3038;--revpick-bg:rgba(0,212,255,.08);--cmt-active-bg:rgba(0,212,255,.06);--cmt-active-border:rgba(0,212,255,.4);--ghost-hover:rgba(0,212,255,.1);--btn-sec-hover:rgba(0,212,255,.45);--ruletab-hover:rgba(0,212,255,.35);--svc-on-bg:rgba(0,212,255,.18);--toast-border:rgba(0,212,255,.35);--toast-shadow:0 10px 32px rgba(0,212,255,.15);--drawer-bg:rgba(22,27,34,.98);--drawer-shadow:-8px 0 36px rgba(0,0,0,.35);--revdiff-loading:rgba(22,27,34,.82);--graph-link:rgba(230,237,243,.12);--graph-link-active:rgba(0,212,255,.8);--graph-label:#e6edf3;--graph-ring:rgba(230,237,243,.4);  --tab-hover:rgba(28,35,48,.9);--depth3d:rgba(0,212,255,.11);--ambient3d:rgba(168,85,247,.07);--inset-edge3d:rgba(0,212,255,.08);--inset-press3d:rgba(0,180,220,.09);--rim3d:rgba(0,212,255,.22);--stone-fade3d:rgba(168,85,247,.18);--btn-depth3d:rgba(0,160,200,.14);--btn-ambient3d:rgba(0,212,255,.09);--btn-press3d:rgba(0,212,255,.1)}
  *{box-sizing:border-box;margin:0;padding:0}
  body{background:linear-gradient(165deg,var(--bg1) 0%,var(--bg2) 45%,var(--bg3) 100%);color:var(--text);font-family:"PingFang SC","Hiragino Sans GB","Microsoft YaHei",-apple-system,BlinkMacSystemFont,sans-serif;height:100vh;overflow:hidden;display:flex;flex-direction:column;transition:background .35s,color .25s}
  ::-webkit-scrollbar{width:8px;height:8px}
  ::-webkit-scrollbar-thumb{background:var(--scroll-thumb);border-radius:8px}
  ::-webkit-scrollbar-track{background:transparent}
  header{padding:14px 24px;border-bottom:1px solid var(--border);display:flex;align-items:center;gap:14px;background:var(--panel-glass);backdrop-filter:blur(12px);flex-wrap:wrap;box-shadow:var(--shadow-sm)}
  .headbrand{display:flex;flex-direction:column;gap:5px;min-width:180px;max-width:min(520px,46vw)}
  header h1{font-size:17px;font-weight:600;white-space:nowrap;color:var(--text);letter-spacing:.3px}
  .curtopic{display:flex;align-items:baseline;gap:8px;min-width:0}
  .curtopic-lbl{font-size:11px;color:var(--muted);white-space:nowrap;flex-shrink:0;padding:3px 10px;border-radius:999px;background:var(--panel2);border:1px solid var(--border)}
  .curtopic-title{font-size:14px;font-weight:600;color:var(--accent);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0}
  header .meta{color:var(--muted);font-size:12px}
  .toolbar{display:flex;gap:8px;align-items:center}
  .svc{display:inline-flex;align-items:center;gap:7px;cursor:pointer;user-select:none}
  .svc input{display:none}
  .svc .track{width:38px;height:20px;border-radius:20px;background:var(--panel2);border:1px solid var(--border);position:relative;transition:.2s}
  .svc .track::after{content:"";position:absolute;top:2px;left:2px;width:14px;height:14px;border-radius:50%;background:var(--muted);transition:.2s}
  .svc input:checked+.track{background:var(--svc-on-bg);border-color:var(--accent)}
  .svc input:checked+.track::after{left:20px;background:var(--accent)}
  .svc .svclbl{font-size:12px;color:var(--muted)}
  .tabs{display:flex;gap:6px;margin-left:auto;padding:4px;background:var(--panel2);border-radius:999px;border:1px solid var(--border)}
  .tab{padding:7px 16px;border-radius:999px;cursor:pointer;font-size:13px;color:var(--muted);border:1px solid transparent;transition:.2s}
  .tab{transition:background .22s ease,color .22s ease,box-shadow .22s ease,transform .15s ease}
  .tab:hover{background:var(--tab-hover);color:var(--text-soft)}
  .tab.active{background:linear-gradient(135deg,var(--accent),var(--accent2));color:#fff;border-color:transparent;box-shadow:var(--tab-shadow)}
  main{flex:1;overflow:hidden;position:relative}
  .view{position:absolute;inset:0;display:none;overflow:auto;padding:22px}
  .view.active{display:block;animation:viewIn .26s cubic-bezier(.22,1,.36,1) both}
  #graphview.active{display:block;padding:0}
  .stats{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:20px}
  .statcard{padding:14px 20px;min-width:90px;border-radius:22px}
  .statcard .num{font-size:22px;font-weight:600;color:var(--accent);position:relative;z-index:2}
  .statcard .lbl{font-size:12px;color:var(--muted);margin-top:2px;position:relative;z-index:2}
  .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:20px}
  .libempty-wrap{display:flex;align-items:center;justify-content:center;min-height:min(360px,calc(100vh - 340px));grid-column:1/-1;width:100%}
  .libempty{text-align:center;color:var(--muted);font-size:14px;line-height:1.9;padding:24px 20px}
  .libempty .hint-title{font-size:15px;color:var(--text-soft);margin-bottom:6px}
  .card{padding:18px;border-radius:22px;cursor:pointer;position:relative}
  .card .ttl{font-size:15px;font-weight:600;line-height:1.4;margin-bottom:8px;padding-right:20px;color:var(--text);position:relative;z-index:2}
  .card .sub{font-size:12px;color:var(--muted);margin-bottom:8px;position:relative;z-index:2}
  .card .sum{font-size:13px;color:var(--text-soft);line-height:1.6;position:relative;z-index:2}
  .card .tags,.card .pdfbtn,.card .urlbtn{position:relative;z-index:3}
  .card .del{position:absolute;top:10px;right:12px;color:var(--muted);cursor:pointer;font-size:16px;opacity:0;transition:.15s;z-index:4}
  .card:hover .del{opacity:1}
  .card .del:hover{color:var(--rose)}
  .badge{display:inline-block;font-size:11px;padding:3px 10px;border-radius:999px;color:var(--badge-text);font-weight:600;margin-right:6px;opacity:.92}
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
  .legend{position:absolute;left:18px;top:18px;background:var(--float-panel);border:1px solid var(--border);border-radius:var(--radius-sm);padding:12px 14px;font-size:12px;backdrop-filter:blur(10px);box-shadow:var(--shadow-sm)}
  .legend .row{display:flex;align-items:center;gap:8px;margin:4px 0}
  .legend .dot{width:10px;height:10px}
  .hint{position:absolute;right:18px;bottom:18px;color:var(--muted);font-size:12px}
  #drawer{position:absolute;top:0;right:0;width:380px;height:100%;background:var(--drawer-bg);border-left:1px solid var(--border);transform:translateX(100%);transition:transform .28s cubic-bezier(.22,1,.36,1);padding:22px;overflow:auto;z-index:10;box-shadow:var(--drawer-shadow)}
  #drawer.open{transform:translateX(0)}
  #drawer .close{position:absolute;top:14px;right:16px;cursor:pointer;color:var(--muted);font-size:20px;line-height:1}
  #drawer h2{font-size:18px;margin:6px 40px 12px 0;line-height:1.4}
  #drawer .field{margin:12px 0;font-size:13px}
  #drawer .field .k{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.5px;margin-bottom:3px}
  #drawer .links a{display:inline-block;margin:3px 6px 3px 0;padding:3px 9px;background:var(--panel2);border-radius:6px;font-size:12px;color:var(--accent);text-decoration:none;cursor:pointer}
  .empty{color:var(--muted);text-align:center;padding:60px 20px;font-size:14px;line-height:1.8}
  .btn{display:inline-flex;align-items:center;gap:6px;padding:8px 16px;border-radius:999px;font-size:13px;font-weight:600;cursor:pointer;border:1px solid transparent;background:linear-gradient(145deg,var(--accent) 0%,var(--accent2) 100%);color:#fff;text-decoration:none;white-space:nowrap;box-shadow:0 2px 0 var(--btn-depth3d),0 5px 12px var(--btn-ambient3d),inset 0 1px 0 var(--surface-hi,rgba(255,255,255,.28));transition:transform .1s ease-out,box-shadow .1s ease-out,filter .15s}
  .btn:hover:not(:disabled){transform:translateY(-1px);box-shadow:0 3px 0 var(--btn-depth3d),0 8px 16px var(--btn-ambient3d),inset 0 1px 0 var(--surface-hi,rgba(255,255,255,.32))}
  .btn:active:not(:disabled){transform:translateY(1px);box-shadow:0 1px 0 var(--btn-depth3d),0 2px 6px var(--btn-ambient3d),inset 0 2px 4px var(--btn-press3d)}
  .btn.sec{background:linear-gradient(160deg,var(--panel) 0%,var(--panel2) 100%);color:var(--text-soft);border:1px solid var(--rim3d,var(--border));box-shadow:0 2px 0 var(--depth3d),0 4px 10px var(--ambient3d),inset 0 1px 0 var(--surface-hi,rgba(255,255,255,.4))}
  .btn.sec:hover:not(:disabled){border-color:var(--btn-sec-hover);color:var(--accent);transform:translateY(-1px);box-shadow:0 3px 0 var(--depth3d),0 7px 14px var(--ambient3d),inset 0 1px 0 var(--surface-hi,rgba(255,255,255,.45))}
  .btn.sec:active:not(:disabled){transform:translateY(1px);box-shadow:0 1px 0 var(--depth3d),inset 0 2px 4px var(--inset-press3d)}
  .btn.ghost{background:linear-gradient(160deg,var(--panel) 0%,var(--panel2) 100%);color:var(--accent);border:1px solid var(--rim3d,var(--border));box-shadow:0 2px 0 var(--depth3d),0 4px 10px var(--ambient3d),inset 0 1px 0 var(--surface-hi,rgba(255,255,255,.35))}
  .btn.ghost:hover:not(:disabled){background:linear-gradient(160deg,var(--panel) 0%,var(--panel2) 100%);transform:translateY(-1px);box-shadow:0 3px 0 var(--depth3d),0 6px 12px var(--ambient3d),inset 0 1px 0 var(--surface-hi,rgba(255,255,255,.4))}
  .btn.ghost:active:not(:disabled){transform:translateY(1px);box-shadow:0 1px 0 var(--depth3d),inset 0 2px 4px var(--inset-press3d)}
  .btn:disabled{opacity:.5;cursor:not-allowed;transform:none!important}
  .setbox .btn,.setbox-foot .btn,.theme-close-btn,.ruletab,.pdfbtn,.urlbtn{user-select:none}
  .pdfbtn,.urlbtn{margin-top:10px;margin-right:8px;font-size:11px;padding:5px 12px;background:linear-gradient(160deg,var(--panel),var(--panel2));color:var(--accent);border:1px solid var(--rim3d,var(--border));border-radius:10px;cursor:pointer;text-decoration:none;display:inline-block;box-shadow:0 1px 0 var(--depth3d),0 3px 8px var(--ambient3d),inset 0 1px 0 var(--surface-hi,rgba(255,255,255,.35));transition:transform .1s,box-shadow .1s}
  .pdfbtn:hover,.urlbtn:hover{border-color:var(--accent);transform:translateY(-1px)}
  .pdfbtn:active,.urlbtn:active{transform:translateY(1px);box-shadow:0 1px 0 var(--depth3d),inset 0 2px 4px var(--inset-press3d)}
  .urledit{display:flex;gap:8px;align-items:center}
  .urledit input{flex:1;min-width:0;padding:7px 10px;border-radius:8px;border:1px solid var(--border);background:var(--panel2);color:var(--text);font-size:12px}
  #pdfmodal,#setmodal,#startmodal,#rulesmodal,#topicmodal,#querymodal,#lintmodal,#docexportmodal,#doccommitmodal,#dochistorymodal,#thememodal{position:fixed;inset:0;background:var(--modal-backdrop);backdrop-filter:blur(10px);z-index:50;display:flex;flex-direction:column;padding:24px;opacity:0;visibility:hidden;pointer-events:none;transition:opacity .24s ease,visibility .24s ease}
  #pdfmodal.open,#setmodal.open,#startmodal.open,#rulesmodal.open,#topicmodal.open,#querymodal.open,#lintmodal.open,#docexportmodal.open,#doccommitmodal.open,#dochistorymodal.open,#thememodal.open{opacity:1;visibility:visible;pointer-events:auto}
  #pdfmodal.open>.bar,#pdfmodal.open>#pdfframe,.ph-modal.open>.setbox,.ph-modal.open>.setbox-flex{animation:modalPopIn .3s cubic-bezier(.22,1,.36,1) both}
  #pdfmodal.open>#pdfframe{animation-delay:.04s}
  #pdfmodal .bar{display:flex;align-items:center;gap:14px;padding:10px 14px;background:var(--panel);border:1px solid var(--border);border-radius:10px 10px 0 0}
  #pdfmodal .bar .name{font-size:13px;color:var(--text);flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  #pdfmodal .bar .x{cursor:pointer;color:var(--muted);font-size:22px;line-height:1}
  #pdfframe{flex:1;width:100%;border:1px solid var(--border);border-top:none;border-radius:0 0 10px 10px;background:#fff}
  #setmodal,#startmodal,#rulesmodal,#topicmodal,#querymodal,#lintmodal,#docexportmodal,#doccommitmodal,#dochistorymodal,#thememodal{align-items:center;justify-content:center}
  .setbox{background:var(--panel);border:1px solid var(--border);border-radius:var(--radius-lg);padding:26px;width:min(560px,92vw);max-height:88vh;overflow:auto;box-shadow:var(--shadow)}
  .setbox-flex{display:flex;flex-direction:column;padding:0;overflow:hidden;box-shadow:var(--shadow)}
  .setbox-head{padding:22px 26px 0;flex-shrink:0;position:relative}
  .setbox:not(.setbox-flex)::before{content:"";display:block;height:4px;border-radius:var(--radius-lg) var(--radius-lg) 0 0;background:linear-gradient(90deg,var(--accent),var(--accent2),var(--accent3));margin:-26px -26px 18px}
  .setbox-flex .setbox-head::before{content:"";display:block;height:4px;border-radius:var(--radius-lg) var(--radius-lg) 0 0;background:linear-gradient(90deg,var(--accent),var(--accent2),var(--accent3));margin:0 0 16px}
  .setbox-body{padding:8px 26px 12px;overflow-y:auto;flex:1;min-height:0}
  .setbox-foot{padding:14px 26px 20px;border-top:1px solid var(--border);flex-shrink:0;display:flex;gap:12px;justify-content:flex-end;background:linear-gradient(180deg,var(--panel),var(--panel2));border-radius:0 0 var(--radius-lg) var(--radius-lg)}
  .setbox h2{font-size:18px;margin-bottom:6px;font-weight:600;letter-spacing:.2px}
  .setbox p.note{color:var(--muted);font-size:12px;margin-bottom:12px;line-height:1.7}
  .setbox label{display:block;font-size:12px;color:var(--muted);margin:14px 0 5px}
  .setbox input,.setbox select,.setbox textarea{width:100%;padding:10px 12px;border-radius:var(--radius-sm);border:1px solid var(--border);background:var(--panel2);color:var(--text);font-size:13px;box-sizing:border-box;transition:border-color .2s,box-shadow .2s}
  .setbox input:focus,.setbox select:focus,.setbox textarea:focus{outline:none;border-color:var(--focus-border);box-shadow:0 0 0 3px var(--focus-shadow)}
  .setbox .row{display:flex;gap:12px;justify-content:flex-end;margin-top:22px}
  .reqtag{color:var(--rose);margin-left:4px}
  .opttag{color:var(--muted);font-size:11px;margin-left:4px;font-weight:400}
  #toast{position:fixed;left:50%;bottom:28px;transform:translateX(-50%) translateY(20px);background:var(--panel);border:1px solid var(--toast-border);border-radius:999px;padding:12px 22px;font-size:13px;z-index:80;opacity:0;transition:.25s;pointer-events:none;max-width:80vw;box-shadow:var(--toast-shadow)}
  #toast.show{opacity:1;transform:translateX(-50%) translateY(0)}
  #overlay{position:fixed;inset:0;background:var(--overlay-backdrop);backdrop-filter:blur(8px);z-index:70;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:18px;opacity:0;visibility:hidden;pointer-events:none;transition:opacity .22s ease,visibility .22s ease}
  #overlay.open{opacity:1;visibility:visible;pointer-events:auto}
  #overlay.open>.msg,#overlay.open>#progwrap,#overlay.open>#progtext,#overlay.open>#progfail,#overlay.open>.cancelbtn{animation:modalPopIn .26s cubic-bezier(.22,1,.36,1) both}
  .spinner{width:42px;height:42px;border:4px solid var(--border);border-top-color:var(--accent);border-radius:50%;animation:spin 1s linear infinite}
  @keyframes spin{to{transform:rotate(360deg)}}
  @keyframes viewIn{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:translateY(0)}}
  @keyframes modalPopIn{from{opacity:0;transform:scale(.97) translateY(12px)}to{opacity:1;transform:scale(1) translateY(0)}}
  @keyframes rulePanelIn{from{opacity:0;transform:translateX(10px)}to{opacity:1;transform:translateX(0)}}
  @media (prefers-reduced-motion:reduce){.view.active,.ph-modal.open>.setbox,.ph-modal.open>.setbox-flex,#pdfmodal.open>.bar,#pdfmodal.open>#pdfframe,#overlay.open>*,.rule-panel.active,#drawer{animation:none!important;transition:none!important}}
  #overlay .msg{font-size:14px;color:var(--text);max-width:70vw;text-align:center}
  #progwrap{width:300px;height:9px;background:var(--panel2);border:1px solid var(--border);border-radius:6px;overflow:hidden;display:none}
  #progwrap.show{display:block}
  #progbar{height:100%;width:0;background:linear-gradient(90deg,var(--accent),var(--accent2));transition:width .3s;border-radius:6px}
  #progtext{font-size:12px;color:var(--muted)}
  #overlay .cancelbtn{margin-top:8px}
  .dropzone{border:2px dashed var(--dropzone-border);border-radius:var(--radius);padding:32px;text-align:center;color:var(--muted);font-size:13px;margin-bottom:16px;transition:.2s;background:var(--dropzone-bg)}
  .dropzone.drag{border-color:var(--accent);background:var(--dropzone-drag);color:var(--text-soft)}
  .graphfilter{position:absolute;right:18px;top:18px;background:var(--float-panel);border:1px solid var(--border);border-radius:var(--radius-sm);padding:10px 12px;font-size:12px;z-index:2;box-shadow:var(--shadow-sm);backdrop-filter:blur(10px)}
  .graphfilter select{padding:5px 8px;border-radius:6px;background:var(--panel2);border:1px solid var(--border);color:var(--text)}
  .lintlist{font-size:12px;line-height:1.7;color:var(--text)}
  .lintlist li{margin:4px 0}
  .queryans{white-space:pre-wrap;line-height:1.7;font-size:13px;max-height:40vh;overflow:auto;padding:12px;background:var(--panel2);border-radius:8px;border:1px solid var(--border)}
  #docview.active{display:flex;flex-direction:column;padding:0;animation:viewIn .26s cubic-bezier(.22,1,.36,1) both}
  .docbar{display:flex;align-items:center;gap:8px;flex-wrap:wrap;padding:12px 18px;border-bottom:1px solid var(--border);background:var(--panel-glass)}
  .docbar select,.docbar input{padding:6px 10px;border-radius:8px;background:var(--panel2);border:1px solid var(--border);color:var(--text);font-size:13px}
  .doclayout{flex:1;display:grid;grid-template-columns:220px 1fr 300px;min-height:0;overflow:hidden}
  .doclist{border-right:1px solid var(--border);overflow-y:auto;padding:10px}
  .docitem{padding:12px;border-radius:var(--radius-sm);cursor:pointer;margin-bottom:8px;border:1px solid transparent;transition:.2s}
  .docitem:hover,.docitem.active{background:var(--panel2);border-color:var(--cmt-active-border);box-shadow:var(--shadow-sm)}
  .docitem .dt{font-size:13px;font-weight:600}
  .docitem .ds{font-size:11px;color:var(--muted);margin-top:4px}
  .docpreview-wrap{position:relative;overflow:hidden;padding:0;background:var(--doc-preview-bg);min-height:0}
  .dochint{display:none;padding:10px 18px;font-size:13px;color:var(--gold);background:var(--dropzone-drag);border-bottom:1px solid var(--dropzone-border);text-align:center;line-height:1.6}
  .dochint.show{display:block;animation:dochintIn .28s ease}
  @keyframes dochintIn{from{opacity:0;transform:translateY(-6px)}to{opacity:1;transform:none}}
  .docempty{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;text-align:center;color:var(--muted);font-size:14px;line-height:1.8;padding:24px;pointer-events:none;z-index:1}
  .docframe{width:100%;height:100%;border:0;display:block;background:var(--doc-preview-bg)}
  .docpanel{border-left:1px solid var(--border);display:flex;flex-direction:column;min-height:0}
  .docpanel-hd{padding:10px 12px;border-bottom:1px solid var(--border);font-size:12px;color:var(--muted)}
  .docpanel-hdrow{display:flex;align-items:center;justify-content:space-between;gap:10px}
  .docpanel-hdrow .docprogress{font-size:12px;color:var(--accent);white-space:nowrap;flex-shrink:0}
  .docpanel-body{flex:1;overflow-y:auto;padding:8px}
  .cmtitem{padding:12px;border-radius:var(--radius-sm);border:1px solid var(--border);margin-bottom:8px;cursor:pointer;font-size:12px;background:var(--panel);transition:.2s}
  .cmtitem:hover,.cmtitem.active{border-color:var(--cmt-active-border);background:var(--cmt-active-bg);box-shadow:var(--shadow-sm)}
  .cmtitem.done{opacity:.55}
  .cmtitem .ca{color:var(--muted);font-size:11px}
  .cmtrow{display:flex;gap:8px;align-items:flex-start}
  .cmtitem input[type=checkbox]{margin-top:2px;flex-shrink:0;cursor:pointer;accent-color:var(--accent)}
  input[type=checkbox]{accent-color:var(--accent)}
  .cmttext{flex:1;line-height:1.45}
  .docpanel-tip{margin-top:6px;font-size:11px;line-height:1.5;color:var(--muted);font-weight:normal}
  .docgitstatus{margin-left:auto;font-size:12px;color:var(--muted);display:flex;align-items:center;gap:10px;flex-wrap:wrap}
  .docgitstatus.dirty{color:var(--gold)}
  .docgitstatus.clean{color:var(--sage)}
  .docdirtydot{display:inline-block;width:7px;height:7px;border-radius:50%;background:var(--gold);flex-shrink:0}
  .docstash{font-size:12px;color:var(--accent)}
  .docstash a{color:var(--accent);cursor:pointer;text-decoration:underline}
  #dochistorymodal .setbox-flex{width:min(860px,96vw);height:min(72vh,640px);max-height:min(72vh,640px)}
  #dochistorymodal .setbox-body{flex:1;min-height:0;overflow:hidden;display:flex;flex-direction:column}
  #dochistorymodal .setbox-foot{min-height:52px;align-items:center}
  .revlayout{display:grid;grid-template-columns:240px 1fr;gap:0;flex:1;min-height:0;height:100%}
  .revlist{border-right:1px solid var(--border);overflow-y:auto;min-height:0}
  .revpick{padding:10px 12px;border-bottom:1px solid var(--border);cursor:pointer;font-size:12px}
  .revpick:hover,.revpick.active{background:var(--revpick-bg)}
  .revpick.active{border-left:3px solid var(--accent);padding-left:9px}
  .revpick .rm{font-weight:600;margin-bottom:4px}
  .revpick .rs{font-size:11px;color:var(--muted)}
  .revdiffwrap{position:relative;min-height:0;overflow:hidden;display:flex;flex-direction:column}
  .revdiff{overflow-y:auto;padding:12px;font-size:12px;line-height:1.6;flex:1;min-height:0}
  .revdiff-loading{position:absolute;inset:0;background:var(--revdiff-loading);backdrop-filter:blur(4px);display:none;align-items:center;justify-content:center;font-size:12px;color:var(--muted);z-index:2;pointer-events:none}
  .revdiff-loading.show{display:flex}
  .diffblock{margin-bottom:12px;padding:10px;border:1px solid var(--border);border-radius:8px;background:var(--panel2)}
  .diffblock .dk{font-size:11px;color:var(--muted);margin-bottom:6px}
  .diffdel{color:var(--rose);background:rgba(212,137,159,.12);text-decoration:line-through;padding:2px 4px;border-radius:6px;display:block;margin-bottom:4px;white-space:pre-wrap}
  .diffins{color:var(--sage);background:rgba(126,184,154,.14);padding:2px 4px;border-radius:6px;display:block;white-space:pre-wrap}
  .difftodo{font-size:12px;padding:4px 0}
  .difftodo .done{color:var(--sage)}
  .difftodo .pending{color:var(--gold)}
  .progbar-mini{height:4px;background:var(--panel2);border-radius:4px;margin-top:6px;overflow:hidden}
  .progbar-mini i{display:block;height:100%;background:var(--accent)}
  .topicbar{display:flex;align-items:center;gap:8px;flex-wrap:wrap;width:100%;margin:6px 0 2px}
  .topicbar .lbl{font-size:12px;color:var(--muted)}
  .topicpick{position:relative;min-width:180px;max-width:280px;flex:0 1 280px}
  .topicpick-btn{width:100%;display:flex;align-items:center;gap:6px;padding:6px 10px;border-radius:8px;background:var(--panel2);border:1px solid var(--border);color:var(--text);font-size:13px;cursor:pointer;text-align:left}
  .topicpick-btn:hover{border-color:var(--accent)}
  .topicpick-lbl{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0}
  .topicpick-caret{color:var(--muted);font-size:10px;flex-shrink:0}
  .topicpick-menu{position:absolute;top:calc(100% + 4px);left:0;right:0;background:var(--panel);border:1px solid var(--border);border-radius:var(--radius-sm);box-shadow:var(--shadow);max-height:240px;overflow-y:auto;z-index:100;display:none}
  .topicpick.open .topicpick-menu{display:block}
  .topicpick-item{padding:8px 12px;font-size:13px;cursor:pointer;overflow:hidden;white-space:nowrap}
  .topicpick-item:hover,.topicpick-item.active{background:var(--panel2)}
  .topicpick-item.active{color:var(--accent);font-weight:600}
  .topicpick-item .topicpick-text{display:inline-block;white-space:nowrap;will-change:transform}
  .libtabs{display:flex;gap:6px;flex-wrap:wrap;align-items:center;margin:0 0 10px;padding:4px 2px}
  .libtab{display:inline-flex;align-items:center;gap:6px;max-width:min(280px,100%);padding:6px 14px;border-radius:999px;cursor:pointer;font-size:13px;color:var(--muted);background:var(--panel2);border:1px solid var(--border);transition:background .22s ease,color .22s ease,border-color .22s ease,box-shadow .22s ease}
  .libtab:hover{border-color:var(--accent);color:var(--text-soft)}
  .libtab.active{background:linear-gradient(135deg,var(--accent),var(--accent2));color:#fff;border-color:transparent;box-shadow:var(--tab-shadow)}
  .libtab-lbl{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0}
  .libtab .cnt{font-size:11px;padding:1px 7px;border-radius:999px;background:rgba(255,255,255,.18);flex-shrink:0}
  .libtab:not(.active) .cnt{background:var(--panel);color:var(--muted)}
  #rulesmodal,#topicmodal{align-items:center;justify-content:center}
  .ruletabs{display:flex;gap:8px;margin-bottom:12px;flex-wrap:wrap}
  .ruletab{padding:6px 14px;border-radius:999px;cursor:pointer;border:1px solid var(--rim3d,var(--border));font-size:12px;color:var(--text-soft);background:linear-gradient(160deg,var(--panel),var(--panel2));box-shadow:0 2px 0 var(--depth3d),0 4px 10px var(--ambient3d),inset 0 1px 0 var(--surface-hi,rgba(255,255,255,.35));transition:transform .1s,box-shadow .1s,border-color .15s,color .15s}
  .ruletab:hover{border-color:var(--ruletab-hover);color:var(--accent);transform:translateY(-1px)}
  .ruletab:active{transform:translateY(1px);box-shadow:0 1px 0 var(--depth3d),inset 0 2px 4px var(--inset-press3d)}
  .ruletab.active{background:linear-gradient(145deg,var(--accent),var(--accent2));color:#fff;border-color:transparent;box-shadow:0 2px 0 var(--btn-depth3d),0 5px 12px var(--btn-ambient3d),inset 0 1px 0 var(--surface-hi,rgba(255,255,255,.25))}
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
  .rule-panel.active{display:block;animation:rulePanelIn .22s cubic-bezier(.22,1,.36,1) both}
  #rulesmodal .ruleseditor{width:100%;height:100%;min-height:0;padding:10px;border-radius:8px;border:1px solid var(--border);background:var(--panel2);color:var(--text);font-size:12px;font-family:ui-monospace,monospace;resize:none;box-sizing:border-box}
  .ruleseditor{width:100%;min-height:280px;padding:10px;border-radius:8px;border:1px solid var(--border);background:var(--panel2);color:var(--text);font-size:12px;font-family:ui-monospace,monospace;resize:vertical;box-sizing:border-box}
  .setbox-flex .purposeform label:first-child{margin-top:4px}
  .theme-fab{position:fixed;top:72px;right:20px;z-index:45;width:50px;height:50px;border-radius:16px;border:1px solid var(--rim3d,var(--border));cursor:pointer;display:flex;align-items:center;justify-content:center;font-size:22px;background:linear-gradient(155deg,var(--panel) 0%,var(--panel2) 100%);box-shadow:0 3px 0 var(--depth3d),0 7px 16px var(--ambient3d),inset 0 1px 0 var(--surface-hi,rgba(255,255,255,.45));transition:transform .15s,box-shadow .15s}
  .theme-fab:hover{transform:translateY(-1px);box-shadow:0 4px 0 var(--depth3d),0 9px 20px var(--ambient3d),inset 0 1px 0 var(--surface-hi,rgba(255,255,255,.5))}
  .theme-fab:active{transform:translateY(1px);box-shadow:0 1px 0 var(--depth3d),0 4px 10px var(--ambient3d),inset 0 2px 4px var(--inset-press3d)}
  #thememodal .theme-modal-box{box-shadow:0 14px 28px var(--ambient3d),0 4px 10px var(--depth3d),inset 0 1px 0 var(--surface-hi,rgba(255,255,255,.35))}
  .theme-head-row{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;margin-bottom:4px}
  .theme-head-row h2{margin-bottom:0;flex:1}
  .theme-close-btn{width:36px;height:36px;border-radius:12px;border:1px solid var(--rim3d,var(--border));background:linear-gradient(155deg,var(--panel) 0%,var(--panel2) 100%);color:var(--muted);font-size:22px;line-height:1;cursor:pointer;flex-shrink:0;display:flex;align-items:center;justify-content:center;box-shadow:0 2px 0 var(--depth3d),0 4px 10px var(--ambient3d),inset 0 1px 0 var(--surface-hi,rgba(255,255,255,.4));transition:transform .12s,box-shadow .12s,color .12s}
  .theme-close-btn:hover{color:var(--accent);transform:translateY(-1px)}
  .theme-close-btn:active{transform:translateY(1px);box-shadow:0 1px 0 var(--depth3d),inset 0 2px 4px var(--inset-press3d)}
  .stone3d{position:relative;transform-style:preserve-3d;transition:transform .1s ease-out,box-shadow .15s ease-out,border-color .15s;border:1px solid var(--rim3d,var(--border));background:radial-gradient(ellipse 95% 78% at 50% 24%,var(--panel) 0%,var(--panel2) 58%,var(--stone-fade3d,var(--border)) 135%);box-shadow:0 3px 0 var(--depth3d),0 8px 18px var(--ambient3d),inset 0 1px 0 var(--surface-hi,rgba(255,255,255,.42));overflow:hidden;will-change:transform}
  .stone3d::before{content:"";position:absolute;inset:0;border-radius:inherit;background:radial-gradient(ellipse 86% 58% at 50% 22%,var(--surface-hi,rgba(255,255,255,.5)) 0%,transparent 68%);pointer-events:none;z-index:1}
  .stone3d::after{content:"";position:absolute;inset:0;border-radius:inherit;box-shadow:inset 0 -6px 12px var(--inset-edge3d),inset 0 5px 10px var(--surface-hi,rgba(255,255,255,.06)),inset 0 0 0 1px var(--rim3d,var(--border));pointer-events:none;z-index:1}
  .stone3d>*{position:relative;z-index:2}
  .stone3d.stone-locked{transform:perspective(800px) rotateX(.6deg) translateY(.5px)!important;box-shadow:0 1px 0 var(--depth3d),0 4px 10px var(--ambient3d),inset 0 2px 6px var(--inset-press3d),0 0 0 2px var(--focus-shadow);border-color:var(--accent)}
  .themegrid{display:grid;grid-template-columns:repeat(2,1fr);gap:20px}
  .themecard{position:relative;padding:0;border:none;border-radius:24px;cursor:pointer;background:transparent;text-align:left}
  .themecard-inner{padding:18px 18px 16px;border-radius:24px}
  .themecard .ti{font-size:32px;line-height:1;margin-bottom:10px;filter:drop-shadow(0 1px 2px var(--ambient3d))}
  .themecard .tn{font-weight:600;font-size:15px;margin-bottom:4px;color:var(--text)}
  .themecard .td{font-size:12px;color:var(--muted);line-height:1.55}
  .themeswatches{display:flex;gap:8px;margin-top:12px}
  .themeswatch{width:26px;height:26px;border-radius:50%;border:2px solid var(--rim3d,rgba(255,255,255,.35));box-shadow:0 2px 0 var(--depth3d),0 3px 6px var(--ambient3d),inset 0 -2px 5px var(--inset-edge3d),inset 0 2px 4px var(--surface-hi,rgba(255,255,255,.28))}
  .setbox,.setbox-flex{transform-style:preserve-3d}
</style>
</head>
<body>
<header>
  <div class="headbrand">
    <h1>✿ 博士论文 Wiki</h1>
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
    <button class="btn sec" onclick="OpenRules()">🌸 研究规则</button>
  </div>
  <label class="svc" title="本地服务开关"><input type="checkbox" id="svctoggle"><span class="track"></span><span class="svclbl" id="svclbl">服务</span></label>
  <div class="toolbar" id="toolbar">
    <button class="btn" onclick="AddPaper()">🌷 添加文献</button>
    <button class="btn sec" onclick="Analyze()">✨ 智能分析</button>
    <button class="btn sec" onclick="OpenQuery()">💭 知识查询</button>
    <button class="btn sec" onclick="RunLint()">🌿 健康巡检</button>
    <button class="btn sec" onclick="Refresh()">↻ 刷新</button>
    <button class="btn sec" onclick="OpenSettings()">🎀 偏好设置</button>
    <button class="btn sec" onclick="ExportBib()">📎 导出 BibTeX</button>
    <button class="btn sec" onclick="SnapshotTopic()">🫧 备份选题</button>
    <input type="file" id="fileinput" accept=".pdf,.docx,.md,.txt" multiple style="display:none">
  </div>
  <span class="meta" id="metainfo"></span>
  <div class="tabs">
    <div class="tab active" data-view="libview">论文库</div>
    <div class="tab" data-view="graphview">知识图谱</div>
    <div class="tab" data-view="listview">全部页面</div>
    <div class="tab" data-view="docview">文档编辑</div>
  </div>
</header>
<button type="button" class="theme-fab" id="theme_fab" onclick="OpenThemePicker()" title="切换界面主题">🎨</button>
<main>
  <section id="libview" class="view active"><div class="libtabs" id="libtabs"></div><div class="stats" id="statsbar"></div><div class="dropzone" id="dropzone">🌷 拖放 PDF / Word / Markdown 到此处，或点击「添加文献」开始整理</div><div class="grid" id="libgrid"></div></section>
  <section id="graphview" class="view"><canvas id="graphcanvas"></canvas><div class="legend" id="legend"></div><div class="graphfilter"><label>筛选 </label><select id="graph_filter" onchange="ApplyGraphFilter()"><option value="">全部类型</option></select></div><div class="hint">滚轮缩放 · 拖拽平移 · 拖动节点 · 点击查看详情</div></section>
  <section id="listview" class="view"></section>
  <section id="docview" class="view">
    <div class="docbar">
      <button class="btn" onclick="ImportDocx()">🌸 导入 Word</button>
      <button class="btn sec" onclick="ExtractDocComments()">💌 抓取批注</button>
      <button class="btn sec" onclick="OpenDocCommit()">🎀 保存版本</button>
      <button class="btn sec" onclick="OpenDocHistory()">🕯 版本历史</button>
      <button class="btn sec" onclick="OpenDocExport()">🎁 导出文档</button>
      <span id="doc_git_status" class="docgitstatus"></span>
      <span id="doc_stash_hint" class="docstash" style="display:none"></span>
      <input type="file" id="docfileinput" accept=".docx" style="display:none">
    </div>
    <div class="dochint" id="doc_hint_bar"></div>
    <div class="doclayout">
      <aside class="doclist" id="doclist"></aside>
      <div class="docpreview-wrap" id="docpreview_wrap">
        <div class="docempty" id="doc_empty_overlay">暂无文档<br>点击「导入 Word」开始编辑</div>
        <iframe id="doc_frame" class="docframe" title="文档编辑"></iframe>
      </div>
      <aside class="docpanel">
        <div class="docpanel-hd">
          <div class="docpanel-hdrow">
            <div>批注列表</div>
            <span id="doc_progress" class="docprogress"></span>
          </div>
          <div class="docpanel-tip">① 选中文字后用顶栏设置字体/字号/颜色/加粗等 ② 离开输入框自动保存 ③「保存版本」把当前修改存为一个可回看的版本 ④「历史」查看每次改动、可回退到旧版本</div>
        </div>
        <div class="docpanel-body" id="docpanel_list"></div>
      </aside>
    </div>
  </section>
  <div id="drawer"><span class="close" onclick="CloseDrawer()">×</span><div id="drawerbody"></div></div>
  <div id="pdfmodal"><div class="bar"><span class="name" id="pdfname"></span><a class="btn ghost" id="pdfnewtab" target="_blank">在新标签打开 ↗</a><span class="x" onclick="ClosePdf()">×</span></div><iframe id="pdfframe"></iframe></div>
  <div id="doccommitmodal" class="ph-modal"><div class="setbox setbox-flex" style="width:min(640px,94vw)">
    <div class="setbox-head">
      <h2>🎀 保存版本</h2>
      <p class="note">把当前修改保存为一个版本（含批注勾选状态），方便日后查看与回退。快捷键 ⌘/Ctrl+S</p>
    </div>
    <div class="setbox-body">
      <label>本次修改说明 <span class="meta">（必填）</span></label>
      <textarea id="doc_commit_msg" rows="3" placeholder="例如：根据外审意见修改引言与结论" style="width:100%;padding:10px;border-radius:8px;border:1px solid var(--border);background:var(--panel2);color:var(--text);font-family:inherit;box-sizing:border-box"></textarea>
      <label style="margin-top:12px">本次改动预览</label>
      <div id="doc_commit_diff" class="revdiff" style="max-height:220px;border:1px solid var(--border);border-radius:8px"></div>
    </div>
    <div class="setbox-foot">
      <button class="btn ghost" onclick="DiscardWorkingChanges()">丢弃未保存的修改</button>
      <button class="btn ghost" onclick="CloseDocCommit()">取消</button>
      <button class="btn" id="doc_commit_btn" onclick="ConfirmDocCommit()">保存版本</button>
    </div>
  </div></div>
  <div id="dochistorymodal" class="ph-modal"><div class="setbox setbox-flex">
    <div class="setbox-head">
      <h2>🕯 版本历史</h2>
      <p class="note">左侧浏览每次保存的版本，右侧查看改动细节，可与最新版本、当前文稿或最初导入版本对比。</p>
    </div>
    <div class="setbox-body" style="padding:0">
      <div class="revlayout">
        <div class="revlist" id="doc_rev_list"></div>
        <div class="revdiffwrap">
          <div class="revdiff-loading" id="doc_rev_loading">加载中…</div>
          <div class="revdiff" id="doc_rev_diff"><div class="meta">请选择一个版本</div></div>
        </div>
      </div>
    </div>
    <div class="setbox-foot" style="flex-wrap:wrap;gap:8px">
      <select id="doc_compare_base" onchange="ReloadRevisionDiff()" style="padding:6px 10px;border-radius:8px;background:var(--panel2);border:1px solid var(--border);color:var(--text);font-size:12px">
        <option value="parent">相对上一版</option>
        <option value="WORKING">相对当前文稿</option>
        <option value="HEAD">相对最新版本</option>
        <option value="original">相对最初导入</option>
      </select>
      <button class="btn ghost" onclick="ReloadRevisionDiff()">刷新对比</button>
      <button class="btn ghost" onclick="DiscardWorkingChanges(true)">丢弃未保存的修改</button>
      <button class="btn ghost" id="doc_restore_working_btn" style="visibility:hidden;pointer-events:none" onclick="RestoreWorkingCopy()">↩ 返回当前修改</button>
      <button class="btn ghost" id="doc_restore_rev_btn" style="visibility:hidden;pointer-events:none" onclick="RestoreSelectedRevision()">恢复此版本</button>
      <button class="btn ghost" onclick="CloseDocHistory()">关闭</button>
    </div>
  </div></div>
  <div id="docexportmodal" class="ph-modal"><div class="setbox setbox-flex" style="width:min(520px,92vw)">
    <div class="setbox-head">
      <h2>🎁 导出 docx</h2>
      <p class="note">将精心修改后的文档保存到本机文件夹，文件名可自由定制。</p>
    </div>
    <div class="setbox-body">
      <label>文件名</label>
      <input id="docexport_name" placeholder="论文修改稿.docx">
      <label>导出文件夹</label>
      <div class="urledit">
        <input id="docexport_dir" placeholder="选择或输入文件夹路径">
        <button class="btn ghost" onclick="PickExportFolder()">浏览…</button>
      </div>
    </div>
    <div class="setbox-foot"><button class="btn ghost" onclick="CloseDocExport()">取消</button><button class="btn" onclick="ConfirmDocExport()">导出</button></div>
  </div></div>
  <div id="thememodal" class="ph-modal"><div class="setbox setbox-flex theme-modal-box" style="width:min(580px,94vw)">
    <div class="setbox-head">
      <div class="theme-head-row">
        <h2>🎨 界面主题</h2>
        <button type="button" class="theme-close-btn" onclick="CloseThemePicker()" title="关闭">×</button>
      </div>
      <p class="note">四套雅色主题，择一而驻；偏好将自动保存于本机。</p>
    </div>
    <div class="setbox-body">
      <div class="themegrid" id="theme_grid"></div>
    </div>
  </div></div>
  <div id="setmodal" class="ph-modal"><div class="setbox setbox-flex" style="width:min(560px,92vw)">
    <div class="setbox-head">
      <h2>🎀 偏好设置 · 大模型 API</h2>
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
  <div id="topicmodal" class="ph-modal"><div class="setbox setbox-flex" style="width:min(600px,94vw)">
    <div class="setbox-head">
      <h2>🌷 新建选题</h2>
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
  <div id="rulesmodal" class="ph-modal"><div class="setbox setbox-flex">
    <div class="setbox-head">
      <h2>🌸 研究规则</h2>
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
  <div id="querymodal" class="ph-modal"><div class="setbox" style="width:min(640px,94vw)">
    <h2>💭 知识库查询</h2>
    <p class="note">基于已编译 wiki 页面作答，结果可沉淀到 wiki/queries/。</p>
    <label>你的问题</label>
    <textarea id="query_input" style="min-height:88px;width:100%;padding:10px;border-radius:8px;border:1px solid var(--border);background:var(--panel2);color:var(--text);font-family:inherit;box-sizing:border-box" placeholder="例如：行政超载与政策分诊的因果证据有哪些？"></textarea>
    <div id="query_result" class="queryans" style="display:none;margin-top:12px"></div>
    <div class="row"><button class="btn ghost" onclick="CloseQuery()">关闭</button><button class="btn" onclick="SubmitQuery()">提问</button></div>
  </div></div>
  <div id="lintmodal" class="ph-modal"><div class="setbox" style="width:min(640px,94vw);max-height:88vh;overflow:auto">
    <h2>🌿 知识库巡检</h2>
    <div id="lint_body" class="lintlist">加载中…</div>
    <div class="row"><button class="btn ghost" onclick="CloseLint()">关闭</button><button class="btn" onclick="RunLint()">重新巡检</button></div>
  </div></div>
  <div id="startmodal" class="ph-modal"><div class="setbox">
    <h2>🫧 启动本地服务</h2>
    <p class="note">出于浏览器安全限制，网页无法直接启动本机程序。请用以下任一方式开启服务，开启后「添加 / 分析 / 刷新」即可使用：</p>
    <p style="font-size:13px;line-height:2">① 双击项目根目录的 <b>start.command</b><br>② 或复制下面命令到「终端」运行：</p>
    <input id="startcmdbox" readonly onclick="this.select()">
    <div class="row"><button class="btn ghost" onclick="CloseStart()">关闭</button><button class="btn" onclick="CopyStart()">复制命令</button></div>
  </div></div>
  <div id="overlay"><div class="spinner"></div><div class="msg" id="overlaymsg">处理中…</div><div id="progwrap"><div id="progbar"></div></div><div id="progtext"></div><div id="progfail" style="font-size:12px;color:var(--rose);max-width:70vw;text-align:center;display:none"></div><button class="btn ghost cancelbtn" id="ingest_cancel_btn" style="display:none" onclick="CancelIngest()">取消分析</button></div>
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
const THEMES=[
  {id:"fresh",icon:"🍃",name:"青岚",desc:"远山含翠，草木蒙雾；低饱和豆沙绿，久读不累",swatches:["#7a9488","#94a89e","#f3f5f2"]},
  {id:"girly",icon:"🌸",name:"绯霞",desc:"蔷薇暮色，温婉含蓄；柔粉与薰衣草，静而不媚",swatches:["#c9789a","#d9a0b8","#faf6f4"]},
  {id:"boyish",icon:"🌊",name:"沧澜",desc:"沧海长风，沉稳俊逸；靛蓝与琥珀，疏朗有度",swatches:["#3d7dd6","#c8a060","#f0f4fa"]},
  {id:"cool",icon:"✦",name:"玄曜",desc:"星夜幽光，深邃明净；暗色底与霓虹，静而不冷",swatches:["#6ec8e0","#9b7fd4","#161b22"]}
];
function GetThemeId(){return document.documentElement.getAttribute("data-theme")||"girly"}
function GetCssVar(sname){return getComputedStyle(document.documentElement).getPropertyValue(sname).trim()}
function ApplyTheme(sid){
  if(!THEMES.some(t=>t.id===sid))sid="girly";
  document.documentElement.setAttribute("data-theme",sid);
  try{localStorage.setItem("ph_theme",sid)}catch(e){}
  RenderThemeGrid();
  if(CURRENT_DOC)LoadDocEditor(CURRENT_DOC);
  if(canvas)DrawGraph();
}
function RenderThemeGrid(){
  const box=document.getElementById("theme_grid");if(!box)return;
  const scur=GetThemeId();
  box.innerHTML=THEMES.map(t=>`<div class="themecard${t.id===scur?" active":""}" onclick="PickTheme('${t.id}')"><div class="themecard-inner${t.id===scur?" stone-locked":""}"><div class="ti">${t.icon}</div><div class="tn">${Esc(t.name)}</div><div class="td">${Esc(t.desc)}</div><div class="themeswatches">${t.swatches.map(c=>`<span class="themeswatch" style="background:${c}"></span>`).join("")}</div></div></div>`).join("");
  BindAllStone3d();
}
function OpenThemePicker(){
  RenderThemeGrid();
  const ofab=document.getElementById("theme_fab");
  if(ofab)ofab.style.display="none";
  document.getElementById("thememodal").classList.add("open");
}
function CloseThemePicker(){
  document.getElementById("thememodal").classList.remove("open");
  const ofab=document.getElementById("theme_fab");
  if(ofab)ofab.style.display="";
}
function PickTheme(sid){
  ApplyTheme(sid);
  if(document.getElementById("thememodal").classList.contains("open"))RenderThemeGrid();
  Toast("已切换为「"+(THEMES.find(t=>t.id===sid)||{}).name+"」主题");
}
function InitTheme(){ApplyTheme(GetThemeId())}

const STONE_TILT=7;
function BindStone3d(el){
  if(!el||el.dataset.stone3d)return;
  el.dataset.stone3d="1";
  el.classList.add("stone3d");
  function IsLocked(){return el.classList.contains("stone-locked")}
  function OnMove(e){
    if(IsLocked())return;
    const r=el.getBoundingClientRect();
    const nx=(e.clientX-r.left)/r.width-0.5;
    const ny=(e.clientY-r.top)/r.height-0.5;
    const rx=(-ny*STONE_TILT).toFixed(2);
    const ry=(nx*STONE_TILT).toFixed(2);
    const press=(-0.4-Math.hypot(nx,ny)*1.6).toFixed(1);
    el.style.transform=`perspective(820px) rotateX(${rx}deg) rotateY(${ry}deg) translateY(${press}px)`;
  }
  function OnLeave(){if(!IsLocked())el.style.transform=""}
  el.addEventListener("mousemove",OnMove);
  el.addEventListener("mouseleave",OnLeave);
}
function BindAllStone3d(){
  document.querySelectorAll(".card,.statcard,.themecard-inner").forEach(BindStone3d);
  document.querySelectorAll(".themecard.active .themecard-inner").forEach(el=>el.classList.add("stone-locked"));
}
function InitUi3d(){BindAllStone3d()}

/* ---------- 渲染 ---------- */
function RenderStats(){
  const order=["source","concept","entity","rq","experiment","synthesis","comparison","query"];
  let h=`<div class="statcard"><div class="num">${DATA.nodes.length}</div><div class="lbl">页面总数</div></div>`;
  h+=`<div class="statcard"><div class="num">${DATA.edges.length}</div><div class="lbl">关联数</div></div>`;
  order.forEach(t=>{if(DATA.stats[t])h+=`<div class="statcard"><div class="num">${DATA.stats[t]}</div><div class="lbl">${TypeLabel(t)}</div></div>`});
  document.getElementById("statsbar").innerHTML=h;
}
function LibTopicCount(t){
  if(t.id===CURRENT_TOPIC)return (DATA.nodes||[]).filter(n=>n.type==="source").length;
  return t.source_count!=null?t.source_count:0;
}
function RenderLibTabs(){
  const bar=document.getElementById("libtabs");
  if(!bar)return;
  if(!SERVERMODE||!TOPICS.length){bar.style.display="none";return;}
  bar.style.display="";
  bar.innerHTML=TOPICS.map(t=>{
    const slabel=TopicLabel(t)||t.id;
    return `<button type="button" class="libtab${t.id===CURRENT_TOPIC?" active":""}" data-id="${Attr(t.id)}" title="${Esc(slabel)}"><span class="libtab-lbl">${Esc(slabel)}</span><span class="cnt">${LibTopicCount(t)}</span></button>`;
  }).join("");
  bar.querySelectorAll(".libtab").forEach(el=>{el.onclick=()=>PickLibTopic(el.dataset.id)});
}
function PickLibTopic(nid){PickTopic(nid)}
function RenderLibrary(){
  const sources=DATA.nodes.filter(n=>n.type==="source");
  const grid=document.getElementById("libgrid");
  if(!sources.length){
    grid.innerHTML='<div class="libempty-wrap"><div class="libempty"><div class="hint-title">📚 论文库为空</div>点击左上角「＋ 添加文献」上传 PDF、Word 或 Markdown<br>也可拖放到上方区域开始整理</div></div>';
    return;
  }
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
  RenderLibTabs();RenderStats();RenderLibrary();RenderList();
  document.getElementById("metainfo").textContent=(SERVERMODE?"本地服务 · ":"")+"更新于 "+DATA.generated;
  UpdateCurrentTopicDisplay();
  InitUi3d();
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
  RenderLibTabs();
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
    ClearDocEditor();
    await Refresh(true);
    await LoadTopics();
    await LoadDocsList();
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
    RenderTopicSelect();UpdateTopicPickBtn();RenderLibTabs();
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
    CloseNewTopic();ClearDocEditor();
    await Refresh(true);await LoadTopics();await LoadDocsList();
    HideOverlay();Toast("新选题已创建");
  }catch(e){HideOverlay();Toast("创建失败："+e.message)}
}
async function ResetTopic(){
  if(NeedServer())return;
  if(!confirm("确定重置当前选题？\n\n将清空已添加的文献与全部分析页面，研究目标恢复范本；结构规则与工作规范保留不变。"))return;
  ShowOverlay("正在重置…");
  try{
    await Api("/api/topics/reset",{});
    ClearDocEditor();
    await Refresh(true);await LoadTopics();await LoadDocsList();
    HideOverlay();Toast("当前选题已重置");
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
    const panel=document.getElementById("rule_"+k+"_panel");
    if(!panel)return;
    panel.classList.remove("active");
    if(k===stab){void panel.offsetWidth;panel.classList.add("active")}
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
  if(!SERVERMODE){if(!silent)Toast("当前为离线只读页面，请在应用中操作以刷新");return}
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
    if(r.saved)Toast("已保存到「问答」记录");
    await Refresh(true);
  }catch(e){HideOverlay();Toast("查询失败："+e.message)}
}
function CloseLint(){document.getElementById("lintmodal").classList.remove("open")}
function RenderLintReport(r){
  let h="<ul>";
  h+="<li>无链接的孤立页面："+(r.orphans?r.orphans.length:0);
  if(r.orphans&&r.orphans.length)h+=" — "+r.orphans.slice(0,8).map(x=>Esc(x.id)).join(", ");
  h+="</li><li>失效链接："+(r.dead_links?r.dead_links.length:0);
  if(r.dead_links&&r.dead_links.length)h+="<br>"+r.dead_links.slice(0,6).map(x=>Esc(x.page)+"→"+Esc(x.link)).join("<br>");
  h+="</li><li>页面信息（标题/标签等）缺失："+(r.frontmatter_issues?r.frontmatter_issues.length:0)+"</li>";
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
  const bcascade=confirm("是否同时删除关联的知识页？\n\n确定 = 一并删除引用了该文献的知识页\n取消 = 只删原文件与这篇文献的摘要页");
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
  {name:"⚡ Pollinations（免注册·直接可用）",base_url:"https://text.pollinations.ai/openai",model:"openai",noauth:true,hint:"公共端点，无需注册/无需 Key，只填选题名即可分析。匿名约每 15 秒 1 次请求，遇繁忙会自动等待重试；若多次提示「限流/繁忙」，请稍后再试，或改用下方带 Key 的免费模型（更稳定，注册约 1 分钟）。"},
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

/* ---------- 文档编辑 ---------- */
let CURRENT_DOC="",DOC_DETAIL=null,SELECTED_COMMENT=null,SELECTED_PARA=-1,DOC_MSG_BOUND=false,DOC_SELECTED_REV=null,DOC_REV_CACHE=null,DOC_SWITCH_GEN=0;
const DOC_NEED_MSGS={commit:"请先导入 Word 文档并选择，再保存版本",history:"请先导入 Word 文档并选择，再查看版本历史",export:"请先导入 Word 文档并选择，再导出",extract:"请先导入 Word 文档并选择，再抓取批注"};
function ShowDocHint(smsg,nms){
  const el=document.getElementById("doc_hint_bar");
  if(!el)return;
  el.textContent=smsg;
  el.classList.add("show");
  clearTimeout(el._t);
  el._t=setTimeout(()=>el.classList.remove("show"),nms||4500);
}
function HideDocHint(){
  const el=document.getElementById("doc_hint_bar");
  if(!el)return;
  el.classList.remove("show");
  clearTimeout(el._t);
}
function UpdateDocEmptyHint(){
  const overlay=document.getElementById("doc_empty_overlay");
  if(overlay)overlay.style.display=CURRENT_DOC?"none":"flex";
  if(CURRENT_DOC)HideDocHint();
}
function NeedDoc(saction){
  if(CURRENT_DOC)return false;
  ShowDocHint(DOC_NEED_MSGS[saction]||"请先导入 docx 并选择文档");
  return true;
}
function ClearDocEditor(){
  DOC_SWITCH_GEN++;
  CURRENT_DOC="";
  DOC_DETAIL=null;
  SELECTED_COMMENT=null;
  SELECTED_PARA=-1;
  DOC_SELECTED_REV=null;
  DOC_REV_CACHE=null;
  const oiframe=document.getElementById("doc_frame");
  if(oiframe){oiframe.dataset.loadGen="";oiframe.src="about:blank";}
  RenderDocListSidebar([]);
  const opanel=document.getElementById("docpanel_list");
  if(opanel)opanel.innerHTML='<div class="meta">无批注。点「抓取批注」从 docx 提取。</div>';
  const oprog=document.getElementById("doc_progress");
  if(oprog)oprog.textContent="";
  RenderGitStatus(null);
  UpdateDocStashHint(false);
  CloseDocCommit();CloseDocHistory();CloseDocExport();
  UpdateDocEmptyHint();
}
function MarkDocActive(sid){
  document.querySelectorAll(".docitem").forEach(el=>{el.classList.toggle("active",el.dataset.id===sid)});
}
function MarkDocDirty(sid,bdirty){
  const oel=Array.from(document.querySelectorAll(".docitem")).find(el=>el.dataset.id===sid);
  if(!oel)return;
  const odt=oel.querySelector(".dt");
  if(!odt)return;
  let odot=odt.querySelector(".docdirtydot");
  if(bdirty&&!odot)odt.insertAdjacentHTML("afterbegin",'<span class="docdirtydot" title="有未提交修改"></span>');
  else if(!bdirty&&odot)odot.remove();
}
function LoadDocEditor(sid,sver){
  const oiframe=document.getElementById("doc_frame");
  if(!oiframe)return;
  const ngen=++DOC_SWITCH_GEN;
  oiframe.dataset.loadGen=String(ngen);
  const sv=sver?("&v="+encodeURIComponent(sver)):"";
  oiframe.src="/api/docs/editor?id="+encodeURIComponent(sid)+"&theme="+encodeURIComponent(GetThemeId())+sv;
}
function BindDocMessages(){
  if(DOC_MSG_BOUND)return;
  DOC_MSG_BOUND=true;
  window.addEventListener("message",async e=>{
    const d=e.data;if(!d||d.source!=="paper-doc-editor")return;
    if(d.type==="doc-para"){SELECTED_PARA=d.para}
    else if(d.type==="doc-cmt"){FocusComment(d.cid)}
    else if(d.type==="doc-saved"){
      Toast(d.commentId?"已保存并标记批注完成":"段落已保存");
      if(!CURRENT_DOC)return;
      try{
        const detail=await Api("/api/docs/detail?id="+encodeURIComponent(CURRENT_DOC)+"&light=1");
        DOC_DETAIL=detail;RenderDocProgress(detail.progress);RenderDocPanel(detail);
        RenderGitStatus(detail.working_status);
        MarkDocDirty(CURRENT_DOC,detail.working_status&&detail.working_status.is_dirty);
        if(d.commentId)LoadDocEditor(CURRENT_DOC,detail.meta&&detail.meta.updated);
      }catch(err){}
    }else if(d.type==="doc-error"){Toast("保存失败："+d.msg)}
  });
}
function RenderDocListSidebar(vdocs){
  const list=document.getElementById("doclist");
  list.innerHTML=(vdocs||[]).map(d=>{
    const sdirty=d.is_dirty?'<span class="docdirtydot" title="有未保存的修改"></span>':'';
    const scmt=d.commit_count?` · ${d.commit_count}个版本`:"";
    return `<div class="docitem${d.id===CURRENT_DOC?" active":""}" data-id="${Attr(d.id)}" onclick="SelectDoc('${Attr(d.id)}')"><div class="dt">${sdirty}${Esc(d.title)}</div><div class="ds">Todo ${d.todo_done}/${d.todo_total}${scmt}</div><div class="progbar-mini"><i style="width:${d.progress||0}%"></i></div></div>`;
  }).join("")||'<div class="meta">暂无文档，请导入 Word</div>';
}
function RenderGitStatus(ws){
  const el=document.getElementById("doc_git_status");
  if(!el)return;
  if(!ws){el.innerHTML="";el.className="docgitstatus";return}
  const shead=ws.head;
  const shash=shead&&shead.hash?shead.hash:"";
  const np=ws.para_change_count||0;
  const nt=ws.todo_change_count||0;
  let shtml="";
  if(ws.is_dirty){
    el.className="docgitstatus dirty";
    const sdirty=np<0?"● 未保存":`● ${np}段 / ${nt}批注 未保存`;
    shtml=shash?`<span>最新版本 <code>${Esc(shash.slice(0,8))}</code></span><span>${sdirty}</span>`:`<span>未保存</span><span>${sdirty}</span>`;
  }else{
    el.className="docgitstatus clean";
    shtml=shash?`<span>最新版本 <code>${Esc(shash.slice(0,8))}</code></span><span>已是最新版本</span>`:(ws.commit_count?`<span>已是最新版本</span>`:`<span>尚无版本</span><span>编辑后点「保存版本」</span>`);
  }
  if(ws.has_working_stash)shtml+=`<span style="color:var(--accent)">· 有暂存的修改</span>`;
  el.innerHTML=shtml;
}
async function RefreshGitStatus(){
  if(!CURRENT_DOC||!SERVERMODE)return;
  try{
    const ws=await Api("/api/docs/status?id="+encodeURIComponent(CURRENT_DOC));
    if(DOC_DETAIL)DOC_DETAIL.working_status=ws;
    RenderGitStatus(ws);
    MarkDocDirty(CURRENT_DOC,ws&&ws.is_dirty);
  }catch(e){}
}
function RenderDiffBlocks(vpara,vtodos,otodomap,oheader){
  let shtml=oheader||"";
  if(!vpara.length&&!vtodos.length)shtml+='<div class="meta">无检测到变更</div>';
  if(vpara.length){
    shtml+='<div class="k" style="margin:12px 0 8px">段落修改</div>';
    shtml+=vpara.map(c=>`<div class="diffblock"><div class="dk">段落 #${c.para_index+1}</div><span class="diffdel">${Esc(c.old||"(空)")}</span><span class="diffins">${Esc(c.new||"(空)")}</span></div>`).join("");
  }
  if(vtodos.length){
    shtml+='<div class="k" style="margin:12px 0 8px">批注状态变更</div>';
    shtml+=vtodos.map(c=>{
      const ot=otodomap[c.comment_id]||{};
      const slabel=Esc((ot.text||c.comment_id||"").slice(0,80));
      const snew=c.new==="done"?"已修改":"待处理";
      const sold=c.old==="done"?"已修改":(c.old?"待处理":"—");
      return `<div class="difftodo"><span class="${c.new==="done"?"done":"pending"}">${slabel}</span>：${sold} → ${snew}</div>`;
    }).join("");
  }
  return shtml;
}
function RenderPendingDiff(ws){
  const box=document.getElementById("doc_commit_diff");
  if(!box)return;
  if(!ws||!ws.is_dirty){box.innerHTML='<div class="meta">当前文稿与最新版本一致，无需保存</div>';return}
  const otodomap={};
  (DOC_DETAIL&&DOC_DETAIL.todos||[]).forEach(t=>{if(t.comment_id)otodomap[t.comment_id]=t});
  const shash=ws.head&&ws.head.hash?ws.head.hash:"";
  const sbase=ws.baseline==="original"?"最初导入":(shash?`最新版本 ${shash.slice(0,8)}`:"最新版本");
  const oheader=`<div class="meta" style="margin-bottom:8px">相对 ${Esc(sbase)}：${ws.para_change_count||0} 段 / ${ws.todo_change_count||0} 批注</div>`;
  box.innerHTML=RenderDiffBlocks(ws.para_changes||[],ws.todo_changes||[],otodomap,oheader);
}
function ImportDocx(){if(NeedServer())return;document.getElementById("docfileinput").click()}
document.getElementById("docfileinput").onchange=async function(){
  const f=this.files[0];this.value="";if(!f)return;
  ShowOverlay("正在导入…");
  try{
    const b64=await FileToBase64(f);
    const r=await Api("/api/docs/import",{name:f.name,data:b64});
    HideOverlay();Toast("已导入："+r.title);await LoadDocsList(r.id);
  }catch(e){HideOverlay();Toast("导入失败："+e.message)}
};
async function LoadDocsList(sselectid){
  if(!SERVERMODE)return;
  try{
    const r=await Api("/api/docs");
    RenderDocListSidebar(r.docs);
    if(sselectid&&sselectid!==CURRENT_DOC)await SelectDoc(sselectid);
    else if(!CURRENT_DOC&&r.docs&&r.docs.length)await SelectDoc(r.docs[0].id);
    else UpdateDocEmptyHint();
  }catch(e){console.error(e)}
}
async function SelectDoc(sid){
  if(!sid||(sid===CURRENT_DOC&&DOC_DETAIL))return;
  CURRENT_DOC=sid;SELECTED_COMMENT=null;SELECTED_PARA=-1;
  UpdateDocEmptyHint();
  MarkDocActive(sid);
  LoadDocEditor(sid);
  BindDocMessages();
  try{
    const d=await Api("/api/docs/detail?id="+encodeURIComponent(sid)+"&light=1");
    if(CURRENT_DOC!==sid)return;
    DOC_DETAIL=d;
    RenderDocProgress(d.progress);
    RenderDocPanel(d);
    RenderGitStatus(d.working_status);
    UpdateDocStashHint(d.has_working_stash);
  }catch(e){Toast("加载文档失败："+e.message)}
}
async function RefreshDocDetail(){
  const sid=CURRENT_DOC;DOC_DETAIL=null;await SelectDoc(sid);
}
function RenderDocProgress(p){
  const el=document.getElementById("doc_progress");
  if(!p||!p.total){el.textContent="";return}
  el.textContent=`批注修改进度 ${p.done}/${p.total}（${p.percent}%）`;
}
function RenderDocPanel(d){
  const box=document.getElementById("docpanel_list");
  const vitems=d.todos||[];
  box.innerHTML=vitems.map(t=>{
    const bc=t.status==="done";
    return `<div class="cmtitem${bc?" done":""}${SELECTED_COMMENT===t.comment_id?" active":""}" onclick="FocusComment('${Attr(t.comment_id)}',${t.para_index})"><div class="cmtrow"><input type="checkbox"${bc?" checked":""} title="勾选表示该批注已修改" onclick="event.stopPropagation();ToggleTodo('${Attr(t.id)}',this.checked)"><span class="cmttext">${Esc(t.text)}</span></div></div>`;
  }).join("")||'<div class="meta">无批注。点「抓取批注」从 Word 文档提取。</div>';
}
function UpdateDocStashHint(bhas){
  const el=document.getElementById("doc_stash_hint");
  if(!el)return;
  if(bhas){
    el.style.display="";
    el.innerHTML='正在查看历史版本 · <a onclick="RestoreWorkingCopy()">返回当前修改</a>';
  }else{el.style.display="none";el.innerHTML=""}
}
async function OpenDocCommit(){
  if(NeedServer()||NeedDoc("commit"))return;
  document.getElementById("doc_commit_msg").value="";
  document.getElementById("doc_commit_diff").innerHTML='<div class="meta">加载中…</div>';
  document.getElementById("doccommitmodal").classList.add("open");
  const obtn=document.getElementById("doc_commit_btn");
  try{
    const ws=await Api("/api/docs/status?id="+encodeURIComponent(CURRENT_DOC));
    if(DOC_DETAIL)DOC_DETAIL.working_status=ws;
    RenderPendingDiff(ws);
    obtn.disabled=!ws.is_dirty;
    obtn.title=ws.is_dirty?"":"当前无变更可提交";
  }catch(e){
    document.getElementById("doc_commit_diff").innerHTML='<div class="meta">加载失败</div>';
    obtn.disabled=false;
  }
}
function CloseDocCommit(){document.getElementById("doccommitmodal").classList.remove("open")}
async function ConfirmDocCommit(){
  if(NeedServer()||!CURRENT_DOC)return;
  const smsg=document.getElementById("doc_commit_msg").value.trim();
  if(!smsg){Toast("请填写本次修改说明");return}
  ShowOverlay("正在保存…");
  try{
    const r=await Api("/api/docs/save",{id:CURRENT_DOC,message:smsg});
    HideOverlay();CloseDocCommit();Toast("已保存版本 "+(r.hash||"").slice(0,8)+"："+r.time);await RefreshDocDetail();
  }catch(e){HideOverlay();Toast("保存失败："+e.message)}
}
async function DiscardWorkingChanges(bfromHistory){
  if(NeedServer()||!CURRENT_DOC)return;
  const ws=(DOC_DETAIL&&DOC_DETAIL.working_status)||{};
  if(!ws.is_dirty){Toast("当前没有未保存的修改");return}
  if(!confirm("丢弃未保存的修改？文稿将回到最新版本（若还没有任何版本则恢复为最初导入）。此操作不可撤销。"))return;
  ShowOverlay("正在重置…");
  try{
    await Api("/api/docs/discard",{id:CURRENT_DOC});
    HideOverlay();
    if(bfromHistory)CloseDocHistory();else CloseDocCommit();
    Toast("已丢弃未提交修改");await RefreshDocDetail();
  }catch(e){HideOverlay();Toast("操作失败："+e.message)}
}
async function OpenDocHistory(){
  if(NeedServer()||NeedDoc("history"))return;
  DOC_SELECTED_REV=null;
  DOC_REV_REQ++;
  SetRevDiffLoading(false);
  SetRevDiffHtml('<div class="meta">请选择一条提交记录</div>');
  try{
    const r=await Api("/api/docs/revisions?id="+encodeURIComponent(CURRENT_DOC));
    DOC_REV_CACHE=r;
    RenderRevList(r.revisions||[]);
    UpdateRevHistoryFoot();
    document.getElementById("dochistorymodal").classList.add("open");
  }catch(e){Toast("加载历史失败："+e.message)}
}
function CloseDocHistory(){document.getElementById("dochistorymodal").classList.remove("open");SetRevDiffLoading(false)}
let DOC_REV_REQ=0;
function SetRevDiffLoading(bshow){
  const el=document.getElementById("doc_rev_loading");
  if(el)el.classList.toggle("show",!!bshow);
}
function SetRevDiffHtml(shtml){
  const box=document.getElementById("doc_rev_diff");
  if(box)box.innerHTML=shtml;
}
function UpdateRevListSelection(){
  document.querySelectorAll("#doc_rev_list .revpick").forEach(el=>{
    el.classList.toggle("active",el.dataset.rev===DOC_SELECTED_REV);
  });
}
function UpdateRevHistoryFoot(){
  const bwork=DOC_SELECTED_REV==="WORKING";
  const bsel=!!DOC_SELECTED_REV;
  const orev=document.getElementById("doc_restore_rev_btn");
  const ostash=document.getElementById("doc_restore_working_btn");
  if(orev)orev.style.visibility=(bsel&&!bwork)?"visible":"hidden";
  if(orev)orev.style.pointerEvents=(bsel&&!bwork)?"auto":"none";
  if(ostash&&DOC_REV_CACHE)ostash.style.visibility=DOC_REV_CACHE.has_working_stash?"visible":"hidden";
  if(ostash&&DOC_REV_CACHE)ostash.style.pointerEvents=DOC_REV_CACHE.has_working_stash?"auto":"none";
}
function RenderRevList(vrevs){
  const box=document.getElementById("doc_rev_list");
  let shtml="";
  if(DOC_REV_CACHE&&DOC_REV_CACHE.is_dirty){
    shtml+=`<div class="revpick${DOC_SELECTED_REV==="WORKING"?" active":""}" data-rev="WORKING" onclick="SelectWorkingDiff()"><div class="rm">● 未保存的修改</div><div class="rs">当前文稿相对最新版本</div></div>`;
  }
  if(!vrevs.length&&!shtml){box.innerHTML='<div class="meta" style="padding:12px">尚无保存的版本</div>';return}
  shtml+=vrevs.map(r=>{
    const shash=(r.hash||r.id||"").slice(0,8);
    const sph=(r.parent_hash||(r.parent_id||"").slice(-8));
    const sparent=sph?` ← ${sph.slice(0,8)}`:"";
    return `<div class="revpick${r.id===DOC_SELECTED_REV?" active":""}" data-rev="${Attr(r.id)}" onclick="SelectRevision('${Attr(r.id)}')"><div class="rm">${Esc(r.message||"提交")}</div><div class="rs"><code>${Esc(shash)}</code>${Esc(sparent)} · ${Esc(r.time)} · 批注 ${r.todos_done||0}/${r.todos_total||0} · ${r.para_change_count||0}段/${r.todo_change_count||0}批注</div></div>`;
  }).join("");
  box.innerHTML=shtml;
}
async function SelectWorkingDiff(){
  if(!CURRENT_DOC||DOC_SELECTED_REV==="WORKING")return;
  DOC_SELECTED_REV="WORKING";
  const osel=document.getElementById("doc_compare_base");
  if(!osel.value||osel.value==="parent")osel.value="HEAD";
  UpdateRevListSelection();
  UpdateRevHistoryFoot();
  await LoadWorkingCompare();
}
async function LoadWorkingCompare(){
  const nreq=++DOC_REV_REQ;
  SetRevDiffLoading(true);
  let sb=document.getElementById("doc_compare_base").value;
  if(sb==="parent")sb=(DOC_REV_CACHE&&DOC_REV_CACHE.head&&DOC_REV_CACHE.head.id)||"original";
  try{
    const d=await Api("/api/docs/compare?id="+encodeURIComponent(CURRENT_DOC)+"&a=WORKING&b="+encodeURIComponent(sb));
    if(nreq!==DOC_REV_REQ)return;
    RenderCompareDiff(d);
    if(DOC_REV_CACHE)DOC_REV_CACHE.has_working_stash=!!d.has_working_stash;
    UpdateRevHistoryFoot();
  }catch(e){
    if(nreq!==DOC_REV_REQ)return;
    SetRevDiffHtml('<div class="meta">加载失败</div>');
  }finally{if(nreq===DOC_REV_REQ)SetRevDiffLoading(false)}
}
async function SelectRevision(srev){
  if(!CURRENT_DOC||DOC_SELECTED_REV===srev)return;
  DOC_SELECTED_REV=srev;
  document.getElementById("doc_compare_base").value="parent";
  UpdateRevListSelection();
  UpdateRevHistoryFoot();
  await ReloadRevisionDiff();
}
async function ReloadRevisionDiff(){
  if(!CURRENT_DOC||!DOC_SELECTED_REV){
    SetRevDiffHtml('<div class="meta">请选择一条提交记录</div>');
    SetRevDiffLoading(false);
    return;
  }
  if(DOC_SELECTED_REV==="WORKING"){await LoadWorkingCompare();return}
  const nreq=++DOC_REV_REQ;
  const sbase=document.getElementById("doc_compare_base").value;
  SetRevDiffLoading(true);
  try{
    if(sbase==="parent"){
      const d=await Api("/api/docs/revision?id="+encodeURIComponent(CURRENT_DOC)+"&rev="+encodeURIComponent(DOC_SELECTED_REV));
      if(nreq!==DOC_REV_REQ)return;
      RenderRevisionDiff(d);
      if(DOC_REV_CACHE)DOC_REV_CACHE.has_working_stash=!!d.has_working_stash;
    }else{
      const d=await Api("/api/docs/compare?id="+encodeURIComponent(CURRENT_DOC)+"&a="+encodeURIComponent(DOC_SELECTED_REV)+"&b="+encodeURIComponent(sbase));
      if(nreq!==DOC_REV_REQ)return;
      RenderCompareDiff(d);
    }
    UpdateRevHistoryFoot();
  }catch(e){
    if(nreq!==DOC_REV_REQ)return;
    SetRevDiffHtml('<div class="meta">加载失败：'+Esc(e.message)+'</div>');
  }finally{if(nreq===DOC_REV_REQ)SetRevDiffLoading(false)}
}
function RenderRevisionDiff(d){
  const olog=d.log||{};
  const otodomap={};
  (d.todos||[]).forEach(t=>{if(t.comment_id)otodomap[t.comment_id]=t});
  const shash=(olog.hash||olog.id||"").slice(0,8);
  const sphash=(olog.parent_hash||"").slice(0,8);
  const oheader=`<div style="margin-bottom:10px"><b>${Esc(olog.message||"")}</b><div class="meta"><code>${Esc(shash)}</code>${sphash?` · 父提交 <code>${Esc(sphash)}</code>`:""} · ${Esc(olog.time||"")} · 批注 ${olog.todos_done||0}/${olog.todos_total||0}</div><div class="meta">相对上一版</div></div>`;
  SetRevDiffHtml(RenderDiffBlocks(olog.para_changes||[],olog.todo_changes||[],otodomap,oheader));
}
function RenderCompareDiff(d){
  const otodomap={};
  (DOC_DETAIL&&DOC_DETAIL.todos||[]).forEach(t=>{if(t.comment_id)otodomap[t.comment_id]=t});
  const sha=String(d.hash_a||d.rev_a||"").slice(0,8);
  const shb=String(d.hash_b||d.rev_b||"").slice(0,8);
  const slabel={WORKING:"当前文稿",HEAD:"最新版本",original:"最初导入"};
  const sb=slabel[d.rev_b]||shb;
  const sa=slabel[d.rev_a]||sha;
  const oheader=`<div style="margin-bottom:10px"><div class="meta"><code>${Esc(sa)}</code> 相对 <code>${Esc(sb)}</code>：${d.para_change_count||0} 段 / ${d.todo_change_count||0} 批注</div></div>`;
  SetRevDiffHtml(RenderDiffBlocks(d.para_changes||[],d.todo_changes||[],otodomap,oheader));
}
async function RestoreSelectedRevision(){
  if(!CURRENT_DOC||!DOC_SELECTED_REV)return;
  if(!confirm("恢复此版本将替换当前文档与批注状态。恢复前当前文稿的修改可稍后用「返回当前修改」找回。继续？"))return;
  ShowOverlay("正在恢复版本…");
  try{
    await Api("/api/docs/restore",{id:CURRENT_DOC,rev:DOC_SELECTED_REV});
    HideOverlay();CloseDocHistory();Toast("已恢复至所选版本");await RefreshDocDetail();
  }catch(e){HideOverlay();Toast("恢复失败："+e.message)}
}
async function RestoreWorkingCopy(){
  if(!CURRENT_DOC)return;
  ShowOverlay("正在恢复文稿…");
  try{
    await Api("/api/docs/restore-working",{id:CURRENT_DOC});
    HideOverlay();CloseDocHistory();Toast("已返回保存前的编辑状态");await RefreshDocDetail();
  }catch(e){HideOverlay();Toast("恢复失败："+e.message)}
}
function FocusComment(scid,npara){
  SELECTED_COMMENT=scid;
  const oc=(DOC_DETAIL&&DOC_DETAIL.comments||[]).find(c=>c.id===scid);
  if(npara===undefined&&oc)npara=oc.para_index;
  const oiframe=document.getElementById("doc_frame");
  if(oiframe&&oiframe.contentWindow&&oiframe.contentWindow.focusPara&&npara!==undefined&&npara>=0){
    oiframe.contentWindow.focusPara(npara,scid);
  }else if(oc){SELECTED_PARA=oc.para_index}
  if(DOC_DETAIL)RenderDocPanel(DOC_DETAIL);
}
async function ToggleTodo(stid,bdone){
  if(!CURRENT_DOC)return;
  try{
    const r=await Api("/api/docs/todo",{id:CURRENT_DOC,todo_id:stid,done:bdone});
    const d=await Api("/api/docs/detail?id="+encodeURIComponent(CURRENT_DOC));
    DOC_DETAIL=d;RenderDocProgress(r.progress);RenderDocPanel(d);RenderGitStatus(d.working_status);
    const lr=await Api("/api/docs");RenderDocListSidebar(lr.docs);
    LoadDocEditor(CURRENT_DOC);
  }catch(e){Toast("更新失败："+e.message)}
}
document.addEventListener("keydown",e=>{
  if(!(e.metaKey||e.ctrlKey)||(e.key!=="s"&&e.key!=="S"))return;
  const odoc=document.getElementById("docview");
  if(!odoc||!odoc.classList.contains("active"))return;
  e.preventDefault();OpenDocCommit();
});
async function ExtractDocComments(){
  if(NeedServer()||NeedDoc("extract"))return;
  ShowOverlay("正在抓取批注…");
  try{
    await Api("/api/docs/extract",{id:CURRENT_DOC});
    HideOverlay();Toast("批注已更新，Todo 已生成");await RefreshDocDetail();
  }catch(e){HideOverlay();Toast("抓取失败："+e.message)}
}
function DefaultExportName(){
  const om=(DOC_DETAIL&&DOC_DETAIL.meta)||{};
  let sname=om.filename||om.title||"export";
  if(!/\.docx$/i.test(sname))sname+=".docx";
  return sname;
}
function OpenDocExport(){
  if(NeedServer()||NeedDoc("export"))return;
  document.getElementById("docexport_name").value=DefaultExportName();
  const slast=localStorage.getItem("doc_export_dir")||"";
  document.getElementById("docexport_dir").value=slast;
  document.getElementById("docexportmodal").classList.add("open");
}
function CloseDocExport(){document.getElementById("docexportmodal").classList.remove("open")}
async function PickExportFolder(){
  try{
    const resp=await fetch("/api/docs/pick-folder",{method:"POST",headers:{"Content-Type":"application/json"},body:"{}"});
    const r=await resp.json();
    if(!resp.ok)throw new Error(r.error||("HTTP "+resp.status));
    if(r.path){
      document.getElementById("docexport_dir").value=r.path;
      localStorage.setItem("doc_export_dir",r.path);
    }
  }catch(e){Toast("选择文件夹失败："+(e.message||"请手动输入路径"))}
}
async function ConfirmDocExport(){
  if(NeedServer()||!CURRENT_DOC)return;
  const sdir=document.getElementById("docexport_dir").value.trim();
  const sname=document.getElementById("docexport_name").value.trim();
  if(!sdir){Toast("请填写导出文件夹");return}
  if(!sname){Toast("请填写文件名");return}
  ShowOverlay("正在导出…");
  try{
    const r=await Api("/api/docs/export",{id:CURRENT_DOC,dir:sdir,filename:sname});
    localStorage.setItem("doc_export_dir",sdir);
    HideOverlay();CloseDocExport();Toast("已导出："+r.path,4000);
  }catch(e){HideOverlay();Toast("导出失败："+e.message)}
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
  const slink=GetCssVar("--graph-link")||"rgba(74,63,71,.14)";
  const slinka=GetCssVar("--graph-link-active")||"rgba(201,120,154,.75)";
  const slabel=GetCssVar("--graph-label")||"#4a3f47";
  const sring=GetCssVar("--graph-ring")||"rgba(74,63,71,.35)";
  links.forEach(l=>{const active=hover&&(l.s.id===hover.id||l.t.id===hover.id);ctx.strokeStyle=active?slinka:slink;ctx.lineWidth=active?2:1;ctx.beginPath();ctx.moveTo(l.s.x,l.s.y);ctx.lineTo(l.t.x,l.t.y);ctx.stroke()});
  nodes.forEach(n=>{const dim=hover&&n!==hover&&!(hoverNeigh&&hoverNeigh.has(n.id));ctx.globalAlpha=dim?0.3:1;ctx.beginPath();ctx.arc(n.x,n.y,n.r,0,6.2832);ctx.fillStyle=TypeColor(n.type);ctx.fill();
    if(!n.ingested){ctx.lineWidth=1.5;ctx.strokeStyle=sring;ctx.setLineDash([3,3]);ctx.stroke();ctx.setLineDash([])}
    if(view.scale>0.6||n.degree>1||n===hover){ctx.globalAlpha=dim?0.35:1;ctx.fillStyle=slabel;ctx.font="12px PingFang SC,sans-serif";ctx.textAlign="center";const lbl=n.title.length>16?n.title.slice(0,15)+"…":n.title;ctx.fillText(lbl,n.x,n.y+n.r+13)}});
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
function SwitchView(vid){
  document.querySelectorAll(".tab").forEach(t=>t.classList.toggle("active",t.dataset.view===vid));
  document.querySelectorAll(".view").forEach(v=>v.classList.remove("active"));
  const view=document.getElementById(vid);
  if(view){
    void view.offsetWidth;
    view.classList.add("active");
  }
  if(vid==="graphview"){if(!canvas)InitGraph();else ResizeCanvas()}
  if(vid==="docview")LoadDocsList();
}
document.querySelectorAll(".tab").forEach(tab=>{tab.onclick=()=>SwitchView(tab.dataset.view)});

if(!SERVERMODE){
  document.getElementById("toolbar").innerHTML='<span class="meta">🌷 只读浏览 · 请打开 <b>Paper-Helper</b> 应用以添加与分析文献</span>';
  const tb=document.getElementById("topicbar");if(tb)tb.style.display="none";
  UpdateCurrentTopicDisplay();
}else{
  RenderTopicSelect();
  UpdateCurrentTopicDisplay();
}
InitTheme();
InitSvcToggle();
InitDropzone();
RenderAll();
if(SERVERMODE){LoadTopics().then(()=>Refresh(true));LoadDocsList();}
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
