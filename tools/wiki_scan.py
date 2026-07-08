#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Wiki 扫描、边推断与选题统计。"""

import os

import topic_manager as topics
import wiki_paths as paths
import wiki_markdown as md
import wiki_source_meta as smeta
import wiki_library as lib


def ScanWiki():
    """扫描 wiki 内容页与 purpose.md，返回节点与边。"""
    vnodes = []
    vrawlinks = []
    vexplicitrels = []

    ousedids = set()
    for fn in smeta.ListSources():
        ometa = md.ParseSourceFilename(fn)
        skey = ometa["key"]
        nseq = 2
        while skey in ousedids:
            skey = "%s-%d" % (ometa["key"], nseq)
            nseq += 1
        ousedids.add(skey)
        vnodes.append({
            "id": skey, "title": ometa["title"] or fn, "type": "source",
            "aliases": [ometa["key"]] if skey != ometa["key"] else [],
            "authors": [ometa["author"]] if ometa["author"] else [],
            "year": ometa["year"], "venue": "", "tags": [], "rawfile": fn,
            "url": smeta.GetPendingSourceUrl(fn),
            "ingested": False,
            "summary": "尚未纳入研究。点击「纳入研究」生成摘要、关联研究问题与综述备忘。",
            "research": {},
        })

    skipfiles = {"index.md", "log.md", "overview.md"}
    for dirpath, vdirs, filenames in os.walk(paths.wikidir):
        if ".trash" in vdirs:
            vdirs.remove(".trash")
        for fn in sorted(filenames):
            if not fn.endswith(".md") or fn.startswith("_") or fn in skipfiles:
                continue
            with open(os.path.join(dirpath, fn), "r", encoding="utf-8") as f:
                ntext = f.read()
            ofm, nbody = md.ParseFrontmatter(ntext)
            nodeid = os.path.splitext(fn)[0]
            stype = ofm.get("type") or ("source" if "/sources/" in dirpath.replace("\\", "/") else "unknown")
            onode = {
                "id": nodeid, "title": ofm.get("title", nodeid), "type": stype,
                "aliases": ofm.get("aliases", []) if isinstance(ofm.get("aliases", []), list) else [],
                "authors": ofm.get("authors", []) if isinstance(ofm.get("authors", []), list) else [],
                "year": ofm.get("year", ""), "venue": ofm.get("venue", ""),
                "tags": ofm.get("tags", []) if isinstance(ofm.get("tags", []), list) else [],
                "url": ofm.get("url", ""),
                "rawfile": "", "ingested": md.SourcePageIngested(ofm, nbody) if stype == "source" else True,
                "summary": md.GetSummary(nbody),
                "research": md.ExtractSourceResearch(nbody) if ofm.get("type") == "source" else {},
                "body": "",
            }
            if stype == "analysis-report":
                try:
                    import research_deep as rdeep
                    nbody = rdeep.NormalizeReportBody(nbody, onode.get("title"))
                except Exception:
                    pass
                onode["has_body"] = bool(nbody.strip())
                onode["body_preview"] = (md.GetSummary(nbody) or StripWikiMarkup(nbody))[:480]
            else:
                onode["has_body"] = False
                onode["body_preview"] = ""
            existing = next((n for n in vnodes if n["id"] == nodeid), None)
            if not existing and nodeid:
                existing = next((n for n in vnodes if n["id"].lower() == nodeid.lower()), None)
            if not existing and nodeid:
                existing = next((n for n in vnodes if nodeid in (n.get("aliases") or [])), None)
            if not existing and nodeid:
                existing = next((n for n in vnodes if nodeid.lower() in [a.lower() for a in (n.get("aliases") or [])]), None)
            if existing:
                md.MergeWikiIntoNode(existing, onode, ofm, nbody)
                lib.EnsureNodeRawfile(existing)
            else:
                lib.EnsureNodeRawfile(onode)
                vnodes.append(onode)
            for t in md.ExtractLinks(nbody):
                vrawlinks.append((nodeid, t))
            if stype in ("comparison", "synthesis", "analysis-report", "query"):
                vexplicitrels.extend(md.ExtractExplicitRelations(nbody))

    purposepath = topics.RulePath("purpose.md")
    if os.path.isfile(purposepath):
        with open(purposepath, "r", encoding="utf-8") as f:
            _, pbody = md.ParseFrontmatter(f.read())
        vnodes.append({
            "id": "purpose", "title": "论文目标 (Purpose)", "type": "purpose",
            "aliases": ["purpose"], "authors": [], "year": "", "venue": "",
            "tags": [], "rawfile": "", "ingested": True, "summary": md.GetSummary(pbody),
        })
        for t in md.ExtractLinks(pbody):
            vrawlinks.append(("purpose", t))

    onodeindex = md.BuildNodeIndex(vnodes)
    onodetype = {n["id"]: n.get("type", "unknown") for n in vnodes}
    oexplicit = {}
    for ex in vexplicitrels:
        srcid = onodeindex.get(ex["source"].strip().lower())
        tgtid = onodeindex.get(ex["target"].strip().lower())
        if not srcid or not tgtid or srcid == tgtid:
            continue
        oexplicit[(srcid, tgtid)] = ex["type"]
    vedges = []
    vseen = set()
    for srcid, target in vrawlinks:
        tgtid = onodeindex.get(target.strip().lower())
        if not tgtid or tgtid == srcid:
            continue
        edgekey = (srcid, tgtid)
        if edgekey in vseen:
            continue
        vseen.add(edgekey)
        stype = onodetype.get(srcid, "unknown")
        ttype = onodetype.get(tgtid, "unknown")
        vetype = oexplicit.pop(edgekey, None)
        vedges.append({
            "source": srcid,
            "target": tgtid,
            "type": vetype or md.InferEdgeType(stype, ttype),
            "src_type": stype,
            "tgt_type": ttype,
            "explicit": bool(vetype),
        })
    for (srcid, tgtid), vetype in oexplicit.items():
        if (srcid, tgtid) in vseen:
            continue
        vseen.add((srcid, tgtid))
        stype = onodetype.get(srcid, "unknown")
        ttype = onodetype.get(tgtid, "unknown")
        vedges.append({
            "source": srcid,
            "target": tgtid,
            "type": vetype,
            "src_type": stype,
            "tgt_type": ttype,
            "explicit": True,
        })
    ndeadlinks = CountDeadLinks(vrawlinks, onodeindex)
    return vnodes, vedges, ndeadlinks


def CountDeadLinks(vrawlinks, onodeindex):
    vseen = set()
    for _, starget in vrawlinks:
        slow = starget.strip().lower()
        if slow not in onodeindex:
            vseen.add(slow)
    return len(vseen)


def CountTopicSources(ntopicid):
    """统计指定选题下的文献数量（与论文库展示一致）。"""
    ntdir = topics.GetTopicDir(ntopicid)
    rdir = os.path.join(ntdir, "raw", "sources")
    wdir = os.path.join(ntdir, "wiki", "sources")
    vkeys = set()
    if os.path.isdir(rdir):
        for fn in os.listdir(rdir):
            if fn.lower().endswith((".pdf", ".docx", ".md", ".txt")) and not fn.startswith("."):
                vkeys.add(md.ParseSourceFilename(fn)["key"])
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

