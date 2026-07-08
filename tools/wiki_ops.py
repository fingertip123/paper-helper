#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Wiki 运维：Lint、Overview、级联删除、Query 上下文、导出/快照。"""
import os
import re
import json
import shutil
from datetime import datetime

import topic_manager as topics
import io_utils

# 由 wiki_core 注入
wikidir = ""
rawsourcesdir = ""
rootdir = ""


def Init(owikidir, orawsourcesdir, orootdir):
    global wikidir, rawsourcesdir, rootdir
    wikidir = owikidir
    rawsourcesdir = orawsourcesdir
    rootdir = orootdir


def _ImportCore():
    import wiki_core as core
    return core


def MetaSkipFiles():
    return {"index.md", "log.md", "overview.md"}


def _PruneTrashDirs(vdirs):
    vdirs[:] = [d for d in vdirs if d != ".trash"]


def ListWikiPages():
    core = _ImportCore()
    vpages = []
    for sroot, vdirs, vfiles in os.walk(wikidir):
        _PruneTrashDirs(vdirs)
        for sname in vfiles:
            if not sname.endswith(".md") or sname.startswith("_") or sname in MetaSkipFiles():
                continue
            spath = os.path.join(sroot, sname)
            with open(spath, "r", encoding="utf-8") as f:
                ntext = f.read()
            ofm, nbody = core.ParseFrontmatter(ntext)
            vpages.append({
                "id": os.path.splitext(sname)[0],
                "path": spath,
                "relpath": os.path.relpath(spath, wikidir),
                "type": ofm.get("type", "unknown"),
                "title": ofm.get("title", os.path.splitext(sname)[0]),
                "frontmatter": ofm,
                "body": nbody,
            })
    return vpages


def RunLintQuick(vnodes, vedges, ndeadlinks=0):
    """轻量巡检摘要（委托 wiki_graph）。"""
    import wiki_graph as graph
    return graph.RunLintQuick(vnodes, vedges, ndeadlinks=ndeadlinks)


def EscapeBibtex(sval):
    sval = str(sval or "")
    return sval.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}").replace("%", "\\%")


def ExportBibtex():
    core = _ImportCore()
    vlines = []
    for p in ListWikiPages():
        if p["type"] != "source":
            continue
        fm = p["frontmatter"]
        skey = EscapeBibtex(p["id"])
        vauthors = fm.get("authors", [])
        if isinstance(vauthors, str):
            vauthors = [vauthors]
        sauthor = " and ".join(EscapeBibtex(a) for a in vauthors) if vauthors else "Unknown"
        syear = EscapeBibtex(fm.get("year", ""))
        stitle = EscapeBibtex(fm.get("title", p["id"]))
        svenue = EscapeBibtex(fm.get("venue", ""))
        surl = EscapeBibtex(fm.get("url", ""))
        vlines.append("@article{%s,\n  author = {%s},\n  title = {%s},\n  year = {%s},\n  journal = {%s},\n  url = {%s}\n}" % (
            skey, sauthor, stitle, syear, svenue, surl))
    return "\n\n".join(vlines)


def RunLintWithOdata(odata):
    """完整巡检（委托 wiki_graph）。"""
    import wiki_graph as graph
    graph.Init(wikidir, rawsourcesdir, rootdir)
    return graph.RunLintWithOdata(odata)


def RunLint():
    import wiki_graph as graph
    graph.Init(wikidir, rawsourcesdir, rootdir)
    return graph.RunLint()


def WriteOverview(odata):
    """写 wiki/overview.md（须传入已构建的 odata）。"""
    ostats = odata.get("stats", {})
    vnodes = odata["nodes"]
    vsources = [n for n in vnodes if n["type"] == "source" and n.get("ingested")]
    vpending = [n for n in vnodes if n["type"] == "source" and not n.get("ingested")]
    stamp = datetime.now().strftime("%Y-%m-%d")

    lines = [
        "---",
        "type: overview",
        "title: 全局概要",
        "updated: %s" % stamp,
        "---",
        "",
        "# Overview · 全局概要",
        "",
        "> 由工具在每次摄入/删除/刷新后自动更新。",
        "",
        "## 现状",
        "",
    ]
    if vsources:
        slist = "、".join("[[%s]]" % n["id"] for n in vsources[:12])
        lines.append("已摄入 %d 篇文献：%s%s。" % (
            len(vsources), slist, "…" if len(vsources) > 12 else ""))
    else:
        lines.append("尚无已纳入研究的文献，请添加 PDF 后点「纳入研究」。")
    if vpending:
        lines.append("待纳入研究 %d 篇。" % len(vpending))

    lines += ["", "## 统计", ""]
    for stype, slabel in [
        ("source", "文献"), ("concept", "概念"), ("entity", "实体"),
        ("rq", "研究问题"), ("experiment", "实验"), ("synthesis", "综合"),
        ("comparison", "对比"), ("analysis-report", "研究报告"), ("query", "问答"),
    ]:
        if ostats.get(stype):
            lines.append("- %s：%d" % (slabel, ostats[stype]))

    vhub = sorted(
        [n for n in vnodes if n["type"] != "source" and n.get("degree", 0) >= 3],
        key=lambda x: -x.get("degree", 0),
    )[:8]
    if vhub:
        lines += ["", "## 关联枢纽", ""]
        for n in vhub:
            lines.append("- [[%s]]（关联 %d）" % (n["id"], n.get("degree", 0)))

    vqueries = [n for n in vnodes if n["type"] == "query"]
    if vqueries:
        lines += ["", "## 问答沉淀", ""]
        for n in sorted(vqueries, key=lambda x: x["id"])[-8:]:
            lines.append("- [[%s]]" % n["id"])

    olint = RunLintWithOdata(odata)
    if olint["orphans"] or olint["dead_links"] or olint["knowledge_gaps"]:
        lines += ["", "## 待关注", ""]
        if olint["orphans"]:
            lines.append("- 孤立页面 %d 个" % len(olint["orphans"]))
        if olint["dead_links"]:
            lines.append("- 死链 %d 处" % len(olint["dead_links"]))
        if olint["knowledge_gaps"]:
            lines.append("- purpose 中引用但缺失的页面 %d 个" % len(olint["knowledge_gaps"]))

    lines += ["", "## 当前论点速览", "", "见 [[purpose]]。", ""]
    opath = os.path.join(wikidir, "overview.md")
    io_utils.AtomicWriteText(opath, "\n".join(lines))


def GenerateOverview():
    """兼容旧调用：内部走 RefreshWiki 缓存。"""
    import wiki_refresh as refresh
    WriteOverview(refresh.GetWikiData())


def FindPagesBySource(skey):
    vpaths = []
    for p in ListWikiPages():
        vsources = p["frontmatter"].get("sources", [])
        if isinstance(vsources, str):
            vsources = [vsources]
        if skey in vsources:
            vpaths.append(p["path"])
    return vpaths


def DeleteSourceCascade(srawfile=None, skey=None, bcascade=True):
    """删除文献：支持 raw 文件名或 source id（重复纳入/BibTeX 占位后 rawfile 可能缺失）。"""
    core = _ImportCore()
    from io_utils import SafeName
    skey = (skey or "").strip()
    sname = SafeName(srawfile or "")
    if sname:
        skey = skey or core.ParseSourceFilename(sname)["key"]
    elif skey:
        sname = core.ResolveRawfileForKey(skey) or ""
    else:
        raise ValueError("缺少文献 id 或 rawfile")
    vremoved = []

    ssrc = os.path.join(wikidir, "sources", skey + ".md")
    if bcascade:
        for spath in FindPagesBySource(skey):
            if spath != ssrc and os.path.isfile(spath):
                os.remove(spath)
                vremoved.append(os.path.relpath(spath, rootdir))

    for srel in (
        "analysis/%s-report.md" % skey,
        "analysis/%s-standard.md" % skey,
        "comparisons/%s-cross.md" % skey,
        "comparisons/%s-draft.md" % skey,
    ):
        spath = os.path.join(wikidir, srel)
        if os.path.isfile(spath):
            os.remove(spath)
            vremoved.append("wiki/" + srel)

    if os.path.isfile(ssrc):
        os.remove(ssrc)
        vremoved.append("wiki/sources/%s.md" % skey)

    for fn in core.ListSources():
        if core.ParseSourceFilename(fn)["key"] != skey:
            continue
        spdf = os.path.join(rawsourcesdir, fn)
        if os.path.isfile(spdf):
            os.remove(spdf)
            if fn not in vremoved:
                vremoved.append(fn)

    ometa = core.ReadSourceMeta()
    vdel = []
    for sk in list(ometa.keys()):
        if sk == core.LIB_TAG_PREFIX + skey:
            vdel.append(sk)
            continue
        if sk.endswith((".pdf", ".docx", ".md", ".txt")) and core.ParseSourceFilename(sk)["key"] == skey:
            vdel.append(sk)
    for sk in vdel:
        ometa.pop(sk, None)
    if vdel:
        core.WriteSourceMeta(ometa)

    return {"key": skey, "removed": vremoved}


def ResolveDoiUrl(surl):
    surl = (surl or "").strip()
    if not surl:
        return ""
    if surl.startswith("10."):
        return "https://doi.org/" + surl
    om = re.search(r"doi\.org/(10\.\S+)", surl, re.I)
    if om:
        return "https://doi.org/" + om.group(1).rstrip("/.,;)")
    return surl


def CollectQueryContext(squestion, nmaxchars=16000):
    import wiki_query as wquery
    return wquery.CollectQueryContext(squestion, nmaxchars=nmaxchars)


def InferQueryLinks(squestion, sanswer, sexclude_id=None):
    """从问答文本推断关联 wiki 页面（wikilink + 标题/id 模糊匹配）。"""
    core = _ImportCore()
    vcited = []
    for stext in (squestion, sanswer):
        for starget in core.ExtractLinks(stext):
            if starget not in vcited and starget != sexclude_id:
                vcited.append(starget)
    import wiki_refresh as refresh
    odata = refresh.GetWikiData()
    stlower = ((squestion or "") + "\n" + (sanswer or "")).lower()
    for n in odata["nodes"]:
        if n["id"] == sexclude_id or n["type"] in ("purpose", "unknown", "query"):
            continue
        for c in [n["id"], n.get("title", "")] + (n.get("aliases") or []):
            sc = (c or "").strip()
            if len(sc) < 4:
                continue
            if sc.lower() in stlower and n["id"] not in vcited:
                vcited.append(n["id"])
                break
    return vcited


def SaveQueryPage(squestion, sanswer):
    import analysis_version as aver
    os.makedirs(os.path.join(wikidir, "queries"), exist_ok=True)
    sid = "q-" + datetime.now().strftime("%Y%m%d-%H%M%S")
    spath = os.path.join(wikidir, "queries", sid + ".md")
    stamp = datetime.now().strftime("%Y-%m-%d")
    vcited = InferQueryLinks(squestion, sanswer)
    slinkblock = "\n".join("- [[%s]]" % c for c in vcited) if vcited else "- （未引用 wiki 页面，可在回答中补充 [[wikilink]]）"
    ofm = {
        "type": "query",
        "title": squestion[:80],
        "sources": vcited[:8],
        "tags": ["问答"],
        "created": stamp,
        "updated": stamp,
        "pipeline": "query",
        "pipeline_version": aver.GetCurrentVersion("query"),
    }
    nbody = (
        "# %s\n\n## 问题\n\n%s\n\n## 回答\n\n%s\n\n## 关联页面\n\n%s\n"
        % (squestion[:80], squestion, sanswer, slinkblock)
    )
    io_utils.AtomicWriteText(spath, io_utils.FormatFrontmatter(ofm, nbody))
    return {"id": sid, "path": os.path.relpath(spath, rootdir), "links": vcited}


def RepairOrphanQueries():
    """为孤立 query 页补全「关联页面」wikilink，消除无出链。"""
    core = _ImportCore()
    vfixed = []
    for p in ListWikiPages():
        if p["type"] != "query":
            continue
        with open(p["path"], "r", encoding="utf-8") as f:
            nfull = f.read()
        ofm, nbody = core.ParseFrontmatter(nfull)
        if "## 关联页面" in nbody:
            continue
        osec = core.ExtractMarkdownSections(nbody)
        vcited = InferQueryLinks(osec.get("问题", ""), osec.get("回答", ""), p["id"])
        if not vcited:
            continue
        slinks = "\n".join("- [[%s]]" % c for c in vcited)
        nbody = nbody.rstrip() + "\n\n## 关联页面\n\n" + slinks + "\n"
        ofm["sources"] = vcited[:8]
        ofm["updated"] = datetime.now().strftime("%Y-%m-%d")
        vfm = []
        for k, v in ofm.items():
            if isinstance(v, list):
                vfm.append("%s: [%s]" % (k, ", ".join(str(x) for x in v)))
            else:
                vfm.append("%s: %s" % (k, v))
        io_utils.AtomicWriteText(p["path"], "---\n" + "\n".join(vfm) + "\n---\n\n" + nbody.lstrip())
        vfixed.append({"id": p["id"], "links": vcited})
    return vfixed


def FixLintIssues():
    """巡检并清理（委托 wiki_graph）。"""
    import wiki_graph as graph
    graph.Init(wikidir, rawsourcesdir, rootdir)
    return graph.FixLint()


def SnapshotTopic():
    topics.EnsureLayout()
    nid = topics.GetCurrentTopicId()
    ntdir = topics.GetTopicDir(nid)
    snaproot = os.path.join(topics.TopicsDir(), ".snapshots")
    os.makedirs(snaproot, exist_ok=True)
    sdst = os.path.join(snaproot, "%s-%s" % (nid, datetime.now().strftime("%Y%m%d-%H%M%S")))
    shutil.copytree(ntdir, sdst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    return {"topic": nid, "path": sdst}
