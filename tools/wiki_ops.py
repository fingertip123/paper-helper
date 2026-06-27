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


def ListWikiPages():
    core = _ImportCore()
    vpages = []
    for sroot, _, vfiles in os.walk(wikidir):
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


def RunLintQuick(vnodes, vedges):
    """轻量巡检摘要（供 BuildData /api/data 附带，避免重复全量扫描）。"""
    olinked = {n["id"]: 0 for n in vnodes}
    for e in vedges:
        olinked[e["source"]] = olinked.get(e["source"], 0) + 1
        olinked[e["target"]] = olinked.get(e["target"], 0) + 1
    norphans = sum(
        1 for n in vnodes
        if n["type"] not in ("purpose", "unknown") and olinked.get(n["id"], 0) == 0
    )
    return {"orphans": norphans, "dead_links": 0, "knowledge_gaps": 0}


def RunLintWithOdata(odata):
    """完整巡检，复用已有 odata（不再 ScanWiki / BuildData）。"""
    core = _ImportCore()
    vnodes = odata["nodes"]
    vedges = odata.get("edges") or []
    onodeids = {n["id"] for n in vnodes}
    olinked = {n["id"]: 0 for n in vnodes}
    for e in vedges:
        olinked[e["source"]] = olinked.get(e["source"], 0) + 1
        olinked[e["target"]] = olinked.get(e["target"], 0) + 1

    vorphans = []
    for n in vnodes:
        if n["type"] in ("purpose", "unknown"):
            continue
        if olinked.get(n["id"], 0) == 0:
            vorphans.append({"id": n["id"], "title": n.get("title", n["id"]), "type": n["type"]})

    onodeindex = core.BuildNodeIndex(vnodes)
    vdead = []
    for p in ListWikiPages():
        for starget in core.ExtractLinks(p["body"]):
            if starget.strip().lower() not in onodeindex:
                vdead.append({"page": p["id"], "link": starget})

    vmissingfm = []
    for p in ListWikiPages():
        if p["type"] == "unknown" or not p["frontmatter"].get("type"):
            vmissingfm.append({"id": p["id"], "issue": "缺少 type"})
        if not p["frontmatter"].get("title"):
            vmissingfm.append({"id": p["id"], "issue": "缺少 title"})

    vgaps = []
    ofields = topics.ParsePurposeFields(topics.ReadText(topics.RulePath("purpose.md")))
    for skey in ("rq1", "rq2", "rq3", "rq4"):
        sval = (ofields.get(skey) or "").strip()
        if not sval or sval in ("（未填写）", "（待填写）"):
            continue
        smatch = re.search(r"\[\[([^\]|]+)", sval)
        srqid = smatch.group(1) if smatch else ""
        if srqid and srqid not in onodeids:
            vgaps.append({"kind": "rq", "field": skey, "text": sval, "missing_page": srqid})

    return {
        "orphans": vorphans,
        "dead_links": vdead,
        "frontmatter_issues": vmissingfm,
        "knowledge_gaps": vgaps,
        "stats": odata.get("stats", {}),
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


def RunLint():
    import wiki_refresh as refresh
    return RunLintWithOdata(refresh.GetWikiData())


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
        ("comparison", "对比"), ("query", "问答"),
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


def DeleteSourceCascade(srawfile, bcascade=True):
    core = _ImportCore()
    sname = os.path.basename(srawfile)
    skey = core.ParseSourceFilename(sname)["key"]
    vremoved = []

    ssrc = os.path.join(wikidir, "sources", skey + ".md")
    if bcascade:
        for spath in FindPagesBySource(skey):
            if spath != ssrc and os.path.isfile(spath):
                os.remove(spath)
                vremoved.append(os.path.relpath(spath, rootdir))

    if os.path.isfile(ssrc):
        os.remove(ssrc)
        vremoved.append("wiki/sources/%s.md" % skey)

    spdf = os.path.join(rawsourcesdir, sname)
    if os.path.isfile(spdf):
        os.remove(spdf)
        vremoved.append(sname)

    ometa = core.ReadSourceMeta()
    if sname in ometa:
        del ometa[sname]
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
    """一键修复可自动处理的巡检项。"""
    import wiki_workflow as wflow
    wflow.Init(wikidir)
    return wflow.FixLintExtended()


def ExportBibtex():
    core = _ImportCore()
    vlines = []
    for p in ListWikiPages():
        if p["type"] != "source":
            continue
        fm = p["frontmatter"]
        skey = p["id"]
        vauthors = fm.get("authors", [])
        if isinstance(vauthors, str):
            vauthors = [vauthors]
        sauthor = " and ".join(vauthors) if vauthors else "Unknown"
        syear = fm.get("year", "")
        stitle = fm.get("title", skey)
        svenue = fm.get("venue", "")
        surl = fm.get("url", "")
        vlines.append("@article{%s,\n  author = {%s},\n  title = {%s},\n  year = {%s},\n  journal = {%s},\n  url = {%s}\n}" % (
            skey, sauthor, stitle, syear, svenue, surl))
    return "\n\n".join(vlines)


def SnapshotTopic():
    topics.EnsureLayout()
    nid = topics.GetCurrentTopicId()
    ntdir = topics.GetTopicDir(nid)
    snaproot = os.path.join(topics.TopicsDir(), ".snapshots")
    os.makedirs(snaproot, exist_ok=True)
    sdst = os.path.join(snaproot, "%s-%s" % (nid, datetime.now().strftime("%Y%m%d-%H%M%S")))
    shutil.copytree(ntdir, sdst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    return {"topic": nid, "path": sdst}
