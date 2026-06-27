#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""知识库查询上下文：种子打分 + wikilink BFS 扩展 + 预算分配。"""
import os
import re

import wiki_core as core
import wiki_refresh as refresh
import topic_manager as topics

_VPRIORITY_TYPES = frozenset({
    "rq", "source", "comparison", "analysis-report", "concept", "synthesis",
})
_VSECTION_HINTS = (
    "方法", "识别", "数据", "结论", "结果", "讨论", "method", "identification",
    "result", "conclusion", "discussion", "finding",
)


def ExpandNeighbors(vseed_ids, vedges, nhops=2):
    """无向 BFS：返回 {node_id: hop_distance}，种子 hop=0。"""
    oadj = {}
    for e in vedges:
        ssrc = e["source"]
        stgt = e["target"]
        oadj.setdefault(ssrc, set()).add(stgt)
        oadj.setdefault(stgt, set()).add(ssrc)
    oseen = {}
    vfrontier = []
    for sid in vseed_ids:
        if sid and sid not in oseen:
            oseen[sid] = 0
            vfrontier.append(sid)
    for nhop in range(1, nhops + 1):
        vnext = []
        for sid in vfrontier:
            for snbr in oadj.get(sid, set()):
                if snbr not in oseen:
                    oseen[snbr] = nhop
                    vnext.append(snbr)
        vfrontier = vnext
    return oseen


def ResolvePagePath(onode):
    """节点 id → wiki 内 .md 路径。"""
    stype = onode.get("type", "unknown")
    sid = onode.get("id", "")
    if stype == "source":
        return os.path.join(core.wikidir, "sources", sid + ".md")
    if stype == "purpose":
        return topics.RulePath("purpose.md")
    if stype == "rq":
        return os.path.join(core.wikidir, "research-questions", sid + ".md")
    sdir = core.typeconfig.get(stype, {}).get("dir", "")
    if sdir:
        return os.path.join(core.wikidir, sdir, sid + ".md")
    return os.path.join(core.wikidir, sid + ".md")


def _SectionPriority(sline):
    slow = sline.lower()
    for shint in _VSECTION_HINTS:
        if shint in slow:
            return 0
    return 1


def ReadPageBudget(spath, nmax, bprefer_sections=False):
    """读页面内容并按预算截断；可选优先保留方法/结论等节。"""
    if not os.path.isfile(spath):
        return ""
    with open(spath, "r", encoding="utf-8") as f:
        stext = f.read()
    if len(stext) <= nmax:
        return stext
    if not bprefer_sections:
        return stext[:nmax]
    vlines = stext.split("\n")
    vchunks = []
    schunk = []
    nlen = 0
    for sline in vlines:
        if sline.startswith("## ") and schunk:
            vchunks.append((_SectionPriority(schunk[0]), "\n".join(schunk)))
            schunk = [sline]
        else:
            schunk.append(sline)
    if schunk:
        vchunks.append((_SectionPriority(schunk[0]), "\n".join(schunk)))
    vchunks.sort(key=lambda x: x[0])
    vout = []
    for _, sblock in vchunks:
        if nlen + len(sblock) + 2 > nmax:
            nremain = nmax - nlen - 2
            if nremain > 120:
                vout.append(sblock[:nremain] + "\n…")
            break
        vout.append(sblock)
        nlen += len(sblock) + 2
    return "\n\n".join(vout) if vout else stext[:nmax]


def _ScoreNode(onode, vwords):
    nscore = 0.0
    stext = (
        (onode.get("title") or "") + " "
        + (onode.get("summary") or "") + " "
        + onode.get("id", "")
    ).lower()
    for w in vwords:
        if w in stext:
            nscore += 2
    if onode.get("type") == "source":
        nscore += 1
    if onode.get("type") == "rq":
        nscore += 2
    if onode.get("type") in ("comparison", "analysis-report"):
        nscore += 1.5
    nscore += float(onode.get("pagerank") or 0) * 8
    return nscore


def _BudgetForHop(nhop, nseed_rank):
    """hop 0 种子按排名分配；扩展页按跳数递减。"""
    if nhop == 0:
        if nseed_rank < 3:
            return 3500
        if nseed_rank < 8:
            return 2200
        return 1500
    if nhop == 1:
        return 1200
    return 600


def CollectQueryContext(squestion, nmaxchars=16000):
    """收集查询上下文：purpose + 种子页 + 1–2 跳 wikilink 邻居。"""
    odata = refresh.GetWikiData()
    vnodes = odata["nodes"]
    vedges = odata["edges"]
    onmap = {n["id"]: n for n in vnodes}
    sq = (squestion or "").lower()
    vwords = [w for w in re.split(r"\W+", sq) if len(w) > 1]

    vexplicit = []
    for starget in core.ExtractLinks(squestion or ""):
        st = starget.strip()
        if st and st not in vexplicit:
            vexplicit.append(st)

    vcandidates = [n for n in vnodes if n.get("type") not in ("purpose", "unknown")]
    vranked = sorted(vcandidates, key=lambda n: _ScoreNode(n, vwords), reverse=True)
    vseeds = []
    for n in vranked[:8]:
        if n["id"] not in vseeds:
            vseeds.append(n["id"])
    for sid in vexplicit:
        if sid not in vseeds:
            vseeds.insert(0, sid)

    oexpanded = ExpandNeighbors(vseeds, vedges, nhops=2)
    for sid in vexplicit:
        oexpanded[sid] = 0

    def SortKey(sid):
        nhop = oexpanded.get(sid, 99)
        onode = onmap.get(sid, {})
        ntype = onode.get("type", "unknown")
        npriority = 0 if ntype in _VPRIORITY_TYPES else 1
        nscore = _ScoreNode(onode, vwords) if onode else 0
        return (nhop, npriority, -nscore)

    vordered = sorted(
        [sid for sid in oexpanded if sid in onmap and sid != "purpose"],
        key=SortKey,
    )

    vchunks = []
    nlen = 0
    spurpose = topics.ReadText(topics.RulePath("purpose.md"))[:2000]
    schunk = "## purpose.md\n" + spurpose
    vchunks.append(schunk)
    nlen += len(schunk)

    oseed_rank = {sid: i for i, sid in enumerate(vseeds)}

    for sid in vordered:
        onode = onmap[sid]
        nhop = oexpanded.get(sid, 99)
        nbudget = _BudgetForHop(nhop, oseed_rank.get(sid, 99))
        spath = ResolvePagePath(onode)
        bsections = nhop == 0 and oseed_rank.get(sid, 99) < 3
        stext = ReadPageBudget(spath, nbudget, bprefer_sections=bsections)
        if not stext.strip():
            continue
        schunk = "## [[%s]]\n%s" % (sid, stext)
        if nlen + len(schunk) + 2 > nmaxchars:
            break
        vchunks.append(schunk)
        nlen += len(schunk) + 2

    return "\n\n".join(vchunks)
