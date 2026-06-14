#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Wiki 运维：Lint、Overview、级联删除、Query 上下文、导出/快照。"""
import os
import re
import json
import shutil
from datetime import datetime

import topic_manager as topics

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


def RunLint():
    core = _ImportCore()
    odata = core.BuildData()
    vnodes = odata["nodes"]
    vedges = odata["edges"]
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


def GenerateOverview():
    core = _ImportCore()
    odata = core.BuildData()
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

    olint = RunLint()
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
    with open(opath, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


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

    spdf = os.path.join(rawsourcesdir, sname)
    if os.path.isfile(spdf):
        os.remove(spdf)
        vremoved.append(sname)

    ssrc = os.path.join(wikidir, "sources", skey + ".md")
    if os.path.isfile(ssrc):
        os.remove(ssrc)
        vremoved.append("wiki/sources/%s.md" % skey)

    if bcascade:
        for spath in FindPagesBySource(skey):
            if spath != ssrc and os.path.isfile(spath):
                os.remove(spath)
                vremoved.append(os.path.relpath(spath, rootdir))

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


def CollectQueryContext(squestion, nmaxchars=12000):
    core = _ImportCore()
    odata = core.BuildData()
    vnodes = odata["nodes"]
    sq = squestion.lower()
    vwords = [w for w in re.split(r"\W+", sq) if len(w) > 1]

    def ScoreNode(n):
        nscore = 0
        stext = (n.get("title", "") + " " + n.get("summary", "") + " " + n["id"]).lower()
        for w in vwords:
            if w in stext:
                nscore += 2
        if n["type"] == "source":
            nscore += 1
        if n["type"] == "rq":
            nscore += 1
        return nscore

    vranked = sorted(
        [n for n in vnodes if n["type"] not in ("purpose",)],
        key=ScoreNode,
        reverse=True,
    )
    vchunks = []
    nlen = 0
    spurpose = topics.ReadText(topics.RulePath("purpose.md"))[:2000]
    vchunks.append("## purpose.md\n" + spurpose)
    nlen += len(vchunks[-1])

    for n in vranked[:20]:
        if ScoreNode(n) <= 0 and len(vchunks) > 1:
            continue
        spath = os.path.join(wikidir, core.typeconfig.get(n["type"], {}).get("dir", ""), n["id"] + ".md")
        if n["type"] == "source":
            spath = os.path.join(wikidir, "sources", n["id"] + ".md")
        elif n["type"] == "purpose":
            spath = topics.RulePath("purpose.md")
        elif n["type"] == "rq":
            spath = os.path.join(wikidir, "research-questions", n["id"] + ".md")
        if not os.path.isfile(spath):
            continue
        with open(spath, "r", encoding="utf-8") as f:
            stext = f.read()[:2500]
        schunk = "## [[%s]]\n%s" % (n["id"], stext)
        if nlen + len(schunk) > nmaxchars:
            break
        vchunks.append(schunk)
        nlen += len(schunk)

    return "\n\n".join(vchunks)


def SaveQueryPage(squestion, sanswer):
    os.makedirs(os.path.join(wikidir, "queries"), exist_ok=True)
    sid = "q-" + datetime.now().strftime("%Y%m%d-%H%M%S")
    spath = os.path.join(wikidir, "queries", sid + ".md")
    stamp = datetime.now().strftime("%Y-%m-%d")
    scontent = (
        "---\ntype: query\ntitle: %s\nsources: []\ntags: [问答]\n"
        "created: %s\nupdated: %s\n---\n\n"
        "# %s\n\n## 问题\n\n%s\n\n## 回答\n\n%s\n"
    ) % (squestion[:80], stamp, stamp, squestion[:80], squestion, sanswer)
    with open(spath, "w", encoding="utf-8") as f:
        f.write(scontent)
    return {"id": sid, "path": os.path.relpath(spath, rootdir)}


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
