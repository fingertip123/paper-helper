#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Wiki 图谱巡检服务（P2）：孤立页、死链、知识空白检测与自动清理。"""
import logging
import re
from datetime import datetime

import topic_manager as topics

logger = logging.getLogger(__name__)

_LINT_KEEP_TYPES = frozenset({"source", "purpose", "rq"})


def Init(owikidir, orawsourcesdir, orootdir):
    """同步路径到 wiki_ops（ListWikiPages 等仍由 ops 提供）。"""
    import wiki_ops as wops
    wops.Init(owikidir, orawsourcesdir, orootdir)


def _Core():
    import wiki_core as core
    return core


def _Ops():
    import wiki_ops as wops
    return wops


def RunLintQuick(vnodes, vedges, ndeadlinks=0):
    """轻量巡检摘要（供 /api/data 附带）。"""
    olinked = {n["id"]: 0 for n in vnodes}
    for e in vedges:
        olinked[e["source"]] = olinked.get(e["source"], 0) + 1
        olinked[e["target"]] = olinked.get(e["target"], 0) + 1
    norphans = sum(
        1 for n in vnodes
        if n["type"] not in ("purpose", "unknown") and olinked.get(n["id"], 0) == 0
    )
    nstale = sum(1 for n in vnodes if n.get("type") == "source" and n.get("pipeline_stale"))
    nknowledge_gaps = 0
    try:
        onodeids = {n["id"] for n in vnodes}
        ofields = topics.ParsePurposeFields(topics.ReadText(topics.RulePath("purpose.md")))
        for skey in ("rq1", "rq2", "rq3", "rq4"):
            sval = (ofields.get(skey) or "").strip()
            if not sval or sval in ("（未填写）", "（待填写）"):
                continue
            smatch = re.search(r"\[\[([^\]|]+)", sval)
            srqid = smatch.group(1) if smatch else ""
            if srqid and srqid not in onodeids:
                nknowledge_gaps += 1
    except (OSError, ValueError, TypeError):
        logger.debug("Lint 知识空白检测失败", exc_info=True)
    return {
        "orphans": norphans,
        "dead_links": ndeadlinks,
        "knowledge_gaps": nknowledge_gaps,
        "stale_pipelines": nstale,
    }


def RunLintWithOdata(odata):
    """完整巡检报告，复用已有 odata。"""
    core = _Core()
    wops = _Ops()
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
    for p in wops.ListWikiPages():
        for starget in core.ExtractLinks(p["body"]):
            if starget.strip().lower() not in onodeindex:
                vdead.append({"page": p["id"], "link": starget})

    vmissingfm = []
    for p in wops.ListWikiPages():
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

    vprunable = [x for x in vorphans if x.get("type") not in _LINT_KEEP_TYPES]

    return {
        "orphans": vorphans,
        "prunable_orphans": vprunable,
        "dead_links": vdead,
        "frontmatter_issues": vmissingfm,
        "knowledge_gaps": vgaps,
        "stats": odata.get("stats", {}),
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


def RunLint(odata=None):
    import wiki_refresh as refresh
    if odata is None:
        odata = refresh.GetWikiData()
    return RunLintWithOdata(odata)


def FixLint(odata=None):
    """巡检并清理：移除孤儿页、剥离死链、合并重复 source。"""
    import wiki_workflow as wflow
    core = _Core()
    wflow.Init(core.wikidir)
    Init(core.wikidir, core.rawsourcesdir, core.rootdir)
    return wflow.FixLintExtended(odata)


def LintIsClean(olint):
    if not olint:
        return True
    return not (
        (olint.get("orphans") or [])
        or (olint.get("prunable_orphans") or [])
        or (olint.get("dead_links") or [])
        or (olint.get("frontmatter_issues") or [])
        or (olint.get("knowledge_gaps") or [])
    )
