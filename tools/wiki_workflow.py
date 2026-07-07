#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""论文工作流：RQ 页维护、章节进度、全文搜索、Lint 扩展修复。"""
import os
import re
import hashlib
from datetime import datetime

import topic_manager as topics
import io_utils

wikidir = ""


def Init(owikidir):
    global wikidir
    wikidir = owikidir


def _Core():
    import wiki_core as core
    return core


def _RqDir():
    return os.path.join(wikidir, "research-questions")


def _ExtractRqIdsFromText(stext):
    core = _Core()
    vids = []
    for starget in core.ExtractLinks(stext or ""):
        st = starget.strip()
        if st and st not in vids:
            vids.append(st)
    return vids


def CollectRqLinksForSource(skey, oresearch=None):
    """从 ingest research 字段与 source 页正文收集 RQ id。"""
    vids = []
    if isinstance(oresearch, dict):
        for sid in oresearch.get("rq_links") or []:
            sid = (sid or "").strip()
            if sid and sid not in vids:
                vids.append(sid)
    spath = os.path.join(wikidir, "sources", skey + ".md")
    if os.path.isfile(spath):
        with open(spath, "r", encoding="utf-8") as f:
            _, nbody = _Core().ParseFrontmatter(f.read())
        osec = _Core().ExtractMarkdownSections(nbody)
        for ssec in ("关联研究问题", "与本论文的关系"):
            for sid in _ExtractRqIdsFromText(osec.get(ssec, "")):
                if sid not in vids:
                    vids.append(sid)
    return vids


def RqTitleFromPurpose(srqid):
    sp = topics.ReadText(topics.RulePath("purpose.md"))
    ofields = topics.ParsePurposeFields(sp)
    for sfield in ("rq1", "rq2", "rq3", "rq4"):
        sval = (ofields.get(sfield) or "").strip()
        if not sval or "[[" + srqid + "]]" not in sval:
            continue
        sm = re.search(r"\[\[%s\]\][^\n]*?[-—：:]\s*(.+)" % re.escape(srqid), sval)
        if sm:
            return sm.group(1).strip()[:80]
        sval = re.sub(r"\[\[[^\]|]+(?:\|[^\]]+)?\]\]", "", sval).strip()
        if sval:
            return sval[:80]
    return srqid.replace("-", " ").title()


def _EnsureRqPage(srqid, ssource_key):
    os.makedirs(_RqDir(), exist_ok=True)
    spath = os.path.join(_RqDir(), srqid + ".md")
    stamp = datetime.now().strftime("%Y-%m-%d")
    if os.path.isfile(spath):
        return spath
    stitle = RqTitleFromPurpose(srqid)
    sbody = (
        "---\n"
        "type: rq\n"
        "title: %s\n"
        "aliases: [%s]\n"
        "status: in-progress\n"
        "sources: []\n"
        "tags: [研究问题]\n"
        "created: %s\n"
        "updated: %s\n"
        "---\n\n"
        "# RQ: %s\n\n"
        "## 问题陈述\n\n"
        "（见 [[purpose]] 中对应 RQ 描述，请在此展开。）\n\n"
        "## 为什么重要\n\n"
        "（待填写）\n\n"
        "## 现有工作如何回答\n\n"
        "## 我的进路 / 假设\n\n"
        "（待填写）\n\n"
        "## 进展与待办\n\n"
        "- [ ] 补充问题陈述\n"
    ) % (stitle, srqid, stamp, stamp, stitle)
    io_utils.AtomicWriteText(spath, sbody)
    return spath


def _AppendSourceToRq(spath, ssource_key, sblurb):
    with open(spath, "r", encoding="utf-8") as f:
        nfull = f.read()
    ofm, nbody = _Core().ParseFrontmatter(nfull)
    sline = "- [[%s]]：%s" % (ssource_key, (sblurb or "（见文献摘要）")[:120])
    if ("[[%s]]" % ssource_key) in nbody:
        return False
    osec = _Core().ExtractMarkdownSections(nbody)
    ssec = osec.get("现有工作如何回答", "")
    if ssec.strip():
        snew = ssec.rstrip() + "\n" + sline + "\n"
    else:
        snew = sline + "\n"
    if "## 现有工作如何回答" in nbody:
        nbody = re.sub(
            r"(## 现有工作如何回答\n)([\s\S]*?)(?=\n## |\Z)",
            r"\1" + snew + "\n",
            nbody,
            count=1,
        )
    else:
        nbody = nbody.rstrip() + "\n\n## 现有工作如何回答\n\n" + snew + "\n"
    vsources = ofm.get("sources", [])
    if isinstance(vsources, str):
        vsources = [vsources]
    if ssource_key not in vsources:
        vsources.append(ssource_key)
    ofm["sources"] = vsources[:12]
    ofm["updated"] = datetime.now().strftime("%Y-%m-%d")
    vfm = []
    for k, v in ofm.items():
        if isinstance(v, list):
            vfm.append("%s: [%s]" % (k, ", ".join(str(x) for x in v)))
        else:
            vfm.append("%s: %s" % (k, v))
    io_utils.AtomicWriteText(spath, "---\n" + "\n".join(vfm) + "\n---\n\n" + nbody.lstrip())
    return True


def _AppendRqToSourcePage(ssource_key, srqid):
    """在 source 页「关联研究问题」追加 wikilink（用户手动分组时）。"""
    spath = os.path.join(wikidir, "sources", ssource_key + ".md")
    if not os.path.isfile(spath):
        return False
    with open(spath, "r", encoding="utf-8") as f:
        nfull = f.read()
    ofm, nbody = _Core().ParseFrontmatter(nfull)
    slink = "[[%s]]" % srqid
    if slink in nbody:
        return False
    if "## 关联研究问题" in nbody:
        nbody = re.sub(
            r"(## 关联研究问题\n)([\s\S]*?)(?=\n## |\Z)",
            lambda m: m.group(1) + (m.group(2).rstrip() + "\n" + slink + "\n\n"),
            nbody,
            count=1,
        )
    else:
        nbody = nbody.rstrip() + "\n\n## 关联研究问题\n\n" + slink + "\n"
    ofm["updated"] = datetime.now().strftime("%Y-%m-%d")
    vfm = []
    for k, v in ofm.items():
        if isinstance(v, list):
            vfm.append("%s: [%s]" % (k, ", ".join(str(x) for x in v)))
        else:
            vfm.append("%s: %s" % (k, v))
    io_utils.AtomicWriteText(spath, "---\n" + "\n".join(vfm) + "\n---\n\n" + nbody.lstrip())
    return True


def LinkSourceToRq(ssource_key, srqid, sblurb=""):
    """用户分组：确保 RQ 页存在并双向链接 source。"""
    if not wikidir or not ssource_key or not srqid:
        return False
    spath = _EnsureRqPage(srqid, ssource_key)
    bupdated = _AppendSourceToRq(spath, ssource_key, sblurb)
    _AppendRqToSourcePage(ssource_key, srqid)
    return bupdated


def SyncRqPages(ssource_key, oresearch=None, sblurb=""):
    """纳入/分析完成后：确保 RQ 页存在并追加支撑文献。"""
    if not wikidir or not ssource_key:
        return {"updated": [], "created": []}
    vrq_ids = CollectRqLinksForSource(ssource_key, oresearch)
    vcreated = []
    vupdated = []
    for srqid in vrq_ids:
        bexisted = os.path.isfile(os.path.join(_RqDir(), srqid + ".md"))
        spath = _EnsureRqPage(srqid, ssource_key)
        if _AppendSourceToRq(spath, ssource_key, sblurb):
            vupdated.append(srqid)
        if not bexisted:
            vcreated.append(srqid)
    return {"created": vcreated, "updated": vupdated, "rq_links": vrq_ids}


def PurposeRqHash(ofields=None):
    if ofields is None:
        ofields = topics.ParsePurposeFields(topics.ReadText(topics.RulePath("purpose.md")))
    parts = []
    for skey in ("rq1", "rq2", "rq3", "rq4", "thesis"):
        parts.append((ofields.get(skey) or "").strip())
    return hashlib.md5("\n".join(parts).encode("utf-8")).hexdigest()


def DetectStaleSources(sold_fields, snew_fields):
    """purpose 中 RQ/论点变更后，返回可能需要重新对齐的已纳入文献 id。"""
    if PurposeRqHash(sold_fields) == PurposeRqHash(snew_fields):
        return []
    import wiki_refresh as refresh
    return [
        n["id"] for n in refresh.GetWikiData()["nodes"]
        if n.get("type") == "source" and n.get("ingested")
    ]


def ParseOutlineChapters(soutline):
    vchapters = []
    for sline in (soutline or "").split("\n"):
        sline = sline.strip()
        if not sline.startswith("- "):
            continue
        bdone = bool(re.match(r"-\s*\[[xX]\]", sline))
        sm = re.match(r"-\s*\[[ xX]\]\s*(.+)", sline)
        if sm:
            vchapters.append({"title": sm.group(1).strip(), "done": bdone})
    return vchapters


def _ChapterKeywords(stitle):
    vwords = []
    for w in re.split(r"[\W_]+", stitle.lower()):
        if len(w) >= 2 and w not in ("第", "章", "节"):
            vwords.append(w)
    for m in re.finditer(r"[\u4e00-\u9fff]{2,}", stitle):
        vwords.append(m.group(0))
    return list(dict.fromkeys(vwords))


def GetChapterProgress(odata=None):
    import wiki_refresh as refresh
    if odata is None:
        odata = refresh.GetWikiData()
    ofields = topics.ParsePurposeFields(topics.ReadText(topics.RulePath("purpose.md")))
    vchapters = ParseOutlineChapters(ofields.get("outline", ""))
    vnodes = odata.get("nodes") or []
    vrqs = [n for n in vnodes if n.get("type") == "rq"]

    for och in vchapters:
        vwords = _ChapterKeywords(och["title"])
        vsources = []
        vcomps = []
        vqueries = []
        vconcepts = []
        for n in vnodes:
            stext = (
                (n.get("title") or "") + " "
                + (n.get("summary") or "") + " "
                + n.get("id", "")
            ).lower()
            if not vwords or not any(w.lower() in stext for w in vwords):
                continue
            stype = n.get("type")
            if stype == "source" and n.get("ingested"):
                vsources.append(n["id"])
            elif stype == "comparison":
                vcomps.append(n["id"])
            elif stype == "query":
                vqueries.append(n["id"])
            elif stype == "concept":
                vconcepts.append(n["id"])
        och["counts"] = {
            "sources": len(vsources),
            "comparisons": len(vcomps),
            "queries": len(vqueries),
            "concepts": len(vconcepts),
        }
        och["sources"] = vsources[:10]
        och["comparisons"] = vcomps[:6]
        och["queries"] = vqueries[:6]

    return {
        "chapters": vchapters,
        "rq_pages": [{"id": n["id"], "title": n.get("title", n["id"])} for n in vrqs],
        "working_title": (ofields.get("working_title") or "").strip(),
    }


def SearchWikiPages(squery, nlimit=40):
    import wiki_refresh as refresh
    import wiki_ops as wops
    core = _Core()
    wops.Init(core.wikidir, core.rawsourcesdir, core.rootdir)
    sq = (squery or "").strip().lower()
    if not sq:
        return []
    vwords = [w for w in re.split(r"\W+", sq) if len(w) > 1]
    odata = refresh.GetWikiData()
    onmap = {n["id"]: n for n in odata["nodes"]}
    vresults = []

    for p in wops.ListWikiPages():
        if p["id"] in ("index", "log", "overview"):
            continue
        stitle = (p.get("title") or p["id"]).lower()
        sid = p["id"].lower()
        ssum = (p["frontmatter"].get("title") or "").lower()
        nscore = 0
        if sq in stitle or sq in sid:
            nscore += 10
        if sq in (p.get("body") or "")[:3000].lower():
            nscore += 4
        for w in vwords:
            if w in stitle or w in sid:
                nscore += 2
            if w in (p.get("body") or "")[:2000].lower():
                nscore += 1
        if nscore <= 0:
            continue
        onode = onmap.get(p["id"], {})
        vresults.append({
            "id": p["id"],
            "title": p.get("title", p["id"]),
            "type": p.get("type", "unknown"),
            "score": nscore,
            "summary": onode.get("summary", "")[:160],
        })
    vresults.sort(key=lambda x: (-x["score"], x["id"]))
    return vresults[:nlimit]


def _FuzzyResolveId(starget, onodeindex):
    slow = starget.strip().lower()
    if slow in onodeindex:
        return onodeindex[slow]
    for sid, sreal in onodeindex.items():
        if slow in sid or sid in slow:
            return sreal
    return ""


def RepairDeadLinks():
    core = _Core()
    import wiki_refresh as refresh
    import wiki_ops as wops
    wops.Init(core.wikidir, core.rawsourcesdir, core.rootdir)
    odata = refresh.GetWikiData()
    onodeindex = core.BuildNodeIndex(odata["nodes"])
    vfixed = []
    for p in wops.ListWikiPages():
        nbody = p["body"]
        bchanged = False
        for starget in core.ExtractLinks(nbody):
            if starget.strip().lower() in onodeindex:
                continue
            sresolved = _FuzzyResolveId(starget, onodeindex)
            if sresolved and sresolved != starget:
                nbody = nbody.replace("[[%s]]" % starget, "[[%s]]" % sresolved)
                bchanged = True
        if bchanged:
            ofm = p["frontmatter"]
            ofm["updated"] = datetime.now().strftime("%Y-%m-%d")
            vfm = []
            for k, v in ofm.items():
                if isinstance(v, list):
                    vfm.append("%s: [%s]" % (k, ", ".join(str(x) for x in v)))
                else:
                    vfm.append("%s: %s" % (k, v))
            io_utils.AtomicWriteText(
                p["path"],
                "---\n" + "\n".join(vfm) + "\n---\n\n" + nbody.lstrip(),
            )
            vfixed.append({"page": p["id"], "action": "dead_link_fuzzy"})
    return vfixed


def RepairOrphanConcepts(odata):
    """为孤立 concept/entity 页补链到 purpose 或关联度最高的 RQ。"""
    core = _Core()
    vnodes = odata["nodes"]
    vedges = odata.get("edges") or []
    olinked = {n["id"]: 0 for n in vnodes}
    for e in vedges:
        olinked[e["source"]] = olinked.get(e["source"], 0) + 1
        olinked[e["target"]] = olinked.get(e["target"], 0) + 1
    vhub = sorted(
        [n for n in vnodes if n.get("type") == "rq"],
        key=lambda x: -x.get("degree", 0),
    )
    shub = vhub[0]["id"] if vhub else "purpose"
    vfixed = []
    for n in vnodes:
        if n.get("type") not in ("concept", "entity"):
            continue
        if olinked.get(n["id"], 0) > 0:
            continue
        spath = os.path.join(wikidir, core.typeconfig.get(n["type"], {}).get("dir", ""), n["id"] + ".md")
        if not os.path.isfile(spath):
            continue
        with open(spath, "r", encoding="utf-8") as f:
            nfull = f.read()
        if ("[[%s]]" % shub) in nfull:
            continue
        _, nbody = core.ParseFrontmatter(nfull)
        nbody = nbody.rstrip() + "\n\n> 关联：[[%s]]\n" % shub
        with open(spath, "r", encoding="utf-8") as f:
            ofm, _ = core.ParseFrontmatter(f.read())
        ofm["updated"] = datetime.now().strftime("%Y-%m-%d")
        vfm = []
        for k, v in ofm.items():
            if isinstance(v, list):
                vfm.append("%s: [%s]" % (k, ", ".join(str(x) for x in v)))
            else:
                vfm.append("%s: %s" % (k, v))
        io_utils.AtomicWriteText(spath, "---\n" + "\n".join(vfm) + "\n---\n\n" + nbody.lstrip())
        vfixed.append({"id": n["id"], "linked_to": shub})
    return vfixed


def FixLintExtended(odata=None):
    core = _Core()
    import wiki_refresh as refresh
    import wiki_ops as wops
    wops.Init(core.wikidir, core.rawsourcesdir, core.rootdir)
    Init(core.wikidir)
    if odata is None:
        odata = refresh.GetWikiData()
    vrep_queries = wops.RepairOrphanQueries()
    vrep_dead = RepairDeadLinks()
    vrep_orphan = RepairOrphanConcepts(odata)
    refresh.RefreshWiki(bwrite_files=True, bforce=True)
    olint = wops.RunLint()
    return {
        "repaired_queries": vrep_queries,
        "repaired_dead_links": vrep_dead,
        "repaired_orphans": vrep_orphan,
        "lint": olint,
    }
