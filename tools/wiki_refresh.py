#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Wiki 统一刷新与扫描缓存（避免单次请求多次 ScanWiki）。"""
import hashlib
import os
import threading

import wiki_core as core
import wiki_ops as wops
import topic_manager as topics

_ocache = {}
_olock = threading.RLock()

_META_SKIP = frozenset({"index.md", "log.md", "overview.md"})


def InvalidateWikiCache(swikidir=None):
    """写入 wiki/raw/purpose 后或切换选题时调用。"""
    with _olock:
        if swikidir:
            _ocache.pop(swikidir, None)
        else:
            _ocache.clear()


def _AppendMtime(parts, spath):
    if os.path.isfile(spath):
        parts.append("%s:%s" % (spath, int(os.path.getmtime(spath))))


def WikiSignature():
    """基于 purpose、wiki 页、raw 文献、source_meta 的 mtime 指纹。"""
    parts = [core.wikidir or ""]
    _AppendMtime(parts, topics.RulePath("purpose.md"))
    _AppendMtime(parts, core.SourceMetaPath())
    if os.path.isdir(core.wikidir):
        for sroot, _, vfiles in os.walk(core.wikidir):
            for sname in sorted(vfiles):
                if not sname.endswith(".md") or sname.startswith("_") or sname in _META_SKIP:
                    continue
                _AppendMtime(parts, os.path.join(sroot, sname))
    if os.path.isdir(core.rawsourcesdir):
        for sname in sorted(os.listdir(core.rawsourcesdir)):
            if sname.startswith("."):
                continue
            _AppendMtime(parts, os.path.join(core.rawsourcesdir, sname))
    return hashlib.md5("\n".join(parts).encode("utf-8")).hexdigest()


def BuildDataFromScan(vnodes, vedges):
    """由 ScanWiki 原始结果构建前端/API 用的 odata（去重、PageRank 等）。"""
    vnodes = core.DedupeSourceNodes(vnodes)
    core.EnrichSourceLibraryMeta(vnodes)
    vedges = core.RefreshEdgeMeta(vnodes, vedges)
    wops.Init(core.wikidir, core.rawsourcesdir, core.rootdir)
    odegree = {n["id"]: 0 for n in vnodes}
    for e in vedges:
        odegree[e["source"]] += 1
        odegree[e["target"]] += 1
    opagerank = core.ComputePageRank(vnodes, vedges)
    for n in vnodes:
        n["degree"] = odegree.get(n["id"], 0)
        n["pagerank"] = round(opagerank.get(n["id"], 0.0), 4)
    ostats = {}
    for n in vnodes:
        ostats[n["type"]] = ostats.get(n["type"], 0) + 1
    olint = wops.RunLintQuick(vnodes, vedges)
    from datetime import datetime
    oprogress = {}
    try:
        import wiki_workflow as wflow
        wflow.Init(core.wikidir)
        oprogress = wflow.GetChapterProgress({"nodes": vnodes, "edges": vedges})
    except Exception:
        pass
    vstale = []
    try:
        import analysis_version as aver
        vstale = aver.DetectStalePipelines(core.wikidir, vnodes)
    except Exception:
        aver = None
    return {
        "nodes": vnodes,
        "edges": vedges,
        "stats": ostats,
        "typeconfig": core.typeconfig,
        "edgeconfig": core.edgeconfig,
        "graphlayers": core.graphlayers,
        "lint": olint,
        "chapters": oprogress,
        "stale_analysis": vstale,
        "stale_pipelines": vstale,
        "pipeline_versions": aver.GetAllVersions() if aver else {},
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


def WriteIndex(vnodes):
    """写 wiki/index.md（不再内部 ScanWiki）。"""
    order = ["rq", "concept", "entity", "source", "experiment", "synthesis", "comparison", "query"]
    from datetime import datetime
    lines = [
        "---",
        "type: index",
        "title: Wiki 目录导航",
        "updated: %s" % datetime.now().strftime("%Y-%m-%d"),
        "---",
        "",
        "# Index · 内容目录",
        "",
        "> 由工具自动生成，每次添加/分析/刷新后更新。",
        "",
    ]
    for stype in order:
        items = [n for n in vnodes if n["type"] == stype]
        if not items:
            continue
        ocfg = core.typeconfig.get(stype, {})
        lines.append("## %s（%d）" % (ocfg.get("label", stype), len(items)))
        lines.append("")
        for n in sorted(items, key=lambda x: x["id"]):
            tail = (" — %s" % n["title"]) if n["title"] and n["title"] != n["id"] else ""
            mark = "" if n.get("ingested", True) else "（待纳入研究）"
            lines.append("- [[%s]]%s%s" % (n["id"], tail, mark))
        lines.append("")
    import io_utils
    io_utils.AtomicWriteText(os.path.join(core.wikidir, "index.md"), "\n".join(lines))


def GetWikiData(bforce=False):
    """返回缓存或 freshly built 的 odata。"""
    swikidir = core.wikidir
    ssig = WikiSignature()
    if not bforce:
        with _olock:
            oentry = _ocache.get(swikidir)
            if oentry and oentry.get("sig") == ssig and oentry.get("odata"):
                return oentry["odata"]
    vnodes, vedges = core.ScanWiki()
    odata = BuildDataFromScan(vnodes, vedges)
    with _olock:
        _ocache[swikidir] = {
            "sig": ssig,
            "vnodes": vnodes,
            "vedges": vedges,
            "odata": odata,
        }
    return odata


def RefreshWiki(bwrite_files=True, bforce=False):
    """单次扫描；可选写 index + overview。"""
    if bforce:
        InvalidateWikiCache(core.wikidir)
    odata = GetWikiData(bforce=bforce)
    if bwrite_files:
        WriteIndex(odata["nodes"])
        wops.Init(core.wikidir, core.rawsourcesdir, core.rootdir)
        wops.WriteOverview(odata)
    return odata
