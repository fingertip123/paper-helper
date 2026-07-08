#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""论文库：rawfile 绑定、去重、阶段元数据。"""

import os
import re

import io_utils
import wiki_paths as paths
import wiki_markdown as md
import wiki_source_meta as smeta
import source_stage as stage


def _NormalizeSourceKey(skey):
    """归一化 source key，便于 vaswani-2017 与 vaswani2017 等变体互认。"""
    return re.sub(r"[^\w]", "", (skey or "").lower())


def BindRawfileToSource(skey, srawfile):
    """将 raw 文件名显式绑定到 source id（重新上传时文件名可能与 id 不一致）。"""
    skey = (skey or "").strip()
    srawfile = io_utils.SafeName(srawfile or "")
    if not skey or not srawfile:
        return
    spath = os.path.join(paths.rawsourcesdir, srawfile)
    if not os.path.isfile(spath):
        return
    oentry = smeta.GetSourceMetaEntry(skey)
    if oentry.get("rawfile") == srawfile:
        return
    oentry["rawfile"] = srawfile
    smeta.SaveSourceMetaEntry(skey, oentry)


def ResolveRawfileForKey(skey):
    """按 source id 在 raw/sources 中查找原始文件名（wiki 页通常不存 rawfile）。"""
    if not skey:
        return ""
    sbound = smeta.GetSourceMetaEntry(skey).get("rawfile", "")
    if sbound:
        spath = os.path.join(paths.rawsourcesdir, sbound)
        if os.path.isfile(spath):
            return sbound
    for fn in smeta.ListSources():
        if md.ParseSourceFilename(fn)["key"] == skey:
            return fn
    snorm = _NormalizeSourceKey(skey)
    if snorm:
        for fn in smeta.ListSources():
            if _NormalizeSourceKey(md.ParseSourceFilename(fn)["key"]) == snorm:
                return fn
    return ""


def EnsureNodeRawfile(onode):
    """已纳入的 source 节点若缺 rawfile，尝试从 raw/sources 按 id/别名 补全。"""
    if onode.get("type") != "source" or onode.get("rawfile"):
        return
    vkeys = [onode.get("id", "")]
    vkeys.extend(onode.get("aliases") or [])
    vseen = set()
    for skey in vkeys:
        skey = (skey or "").strip()
        if not skey or skey in vseen:
            continue
        vseen.add(skey)
        sfile = ResolveRawfileForKey(skey)
        if sfile:
            onode["rawfile"] = sfile
            return



def BuildLibraryGroups(vnodes=None):
    """汇总 RQ / 章节 / 文件夹分组及文献计数。"""
    if vnodes is None:
        import wiki_refresh as refresh
        vnodes = refresh.GetWikiData()["nodes"]
    import wiki_workflow as wflow
    wflow.Init(paths.wikidir)
    oprogress = wflow.GetChapterProgress({"nodes": vnodes})
    ofolders = {}
    orq_counts = {}
    ochapter_counts = {}
    for n in vnodes:
        if n.get("type") != "source":
            continue
        sid = n.get("id", "")
        oentry = smeta.GetSourceMetaEntry(sid)
        for stag in oentry.get("lib_tags") or n.get("lib_tags") or []:
            stag = str(stag).strip()
            if stag:
                ofolders[stag] = ofolders.get(stag, 0) + 1
        for srid in oentry.get("lib_rq") or n.get("lib_rq") or []:
            srid = str(srid).strip()
            if srid:
                orq_counts[srid] = orq_counts.get(srid, 0) + 1
        sch = (oentry.get("lib_chapter") or n.get("lib_chapter") or "").strip()
        if sch:
            ochapter_counts[sch] = ochapter_counts.get(sch, 0) + 1
    vrqs = []
    for r in oprogress.get("rq_pages") or []:
        rid = r.get("id", "")
        vrqs.append({
            "id": rid,
            "title": r.get("title", rid),
            "count": orq_counts.get(rid, 0),
        })
    for rid, ncnt in sorted(orq_counts.items()):
        if not any(x["id"] == rid for x in vrqs):
            vrqs.append({"id": rid, "title": wflow.RqTitleFromPurpose(rid), "count": ncnt})
    vchapters = []
    for ch in oprogress.get("chapters") or []:
        stitle = ch.get("title", "")
        if not stitle:
            continue
        vchapters.append({
            "id": stitle,
            "title": stitle,
            "count": ochapter_counts.get(stitle, 0),
            "done": bool(ch.get("done")),
        })
    for stitle, ncnt in sorted(ochapter_counts.items()):
        if not any(x["id"] == stitle for x in vchapters):
            vchapters.append({"id": stitle, "title": stitle, "count": ncnt, "done": False})
    vfolders = [{"id": f, "title": f, "count": c} for f, c in sorted(ofolders.items(), key=lambda x: x[0])]
    return {"rq": vrqs, "chapters": vchapters, "folders": vfolders}


def HasDeepReportFile(skey):
    """是否已有深度研究报告文件。"""
    if not skey:
        return False
    spath = os.path.join(paths.wikidir, "analysis", skey + "-report.md")
    return os.path.isfile(spath)


def HasStandardReportFile(skey):
    """是否已有标准分析报告文件。"""
    if not skey:
        return False
    spath = os.path.join(paths.wikidir, "analysis", skey + "-standard.md")
    return os.path.isfile(spath)


def _NormalizeTitle(stitle):
    stitle = re.sub(r"[^\w\u4e00-\u9fff]+", "", (stitle or "").lower())
    return stitle[:96]


def _ExtractDoi(onode):
    surl = (onode.get("url") or "").lower()
    om = re.search(r"(10\.\d{4,}/[^\s\"\'<>]+)", surl)
    return om.group(1).rstrip("/.,;)") if om else ""


def _SourceCanonicalScore(onode):
    nscore = 0
    if onode.get("ingested"):
        nscore += 100
    if smeta.FindSourcePagePath(onode.get("id", "")):
        nscore += 50
    if onode.get("rawfile"):
        nscore += 20
    if onode.get("deep_done"):
        nscore += 8
    elif onode.get("standard_done"):
        nscore += 4
    nscore -= len(onode.get("id") or "")
    return nscore


def _MergeSourceMetaEntries(scanon, sother):
    """合并重复 source 的 source_meta（分组标签等）。"""
    if not scanon or not sother or scanon == sother:
        return
    ocanon = smeta.GetSourceMetaEntry(scanon)
    oother = smeta.GetSourceMetaEntry(sother)
    if not oother:
        return
    bchanged = False
    for sk in ("lib_tags", "lib_rq"):
        vmerged = list(dict.fromkeys((ocanon.get(sk) or []) + (oother.get(sk) or [])))
        if vmerged != (ocanon.get(sk) or []):
            ocanon[sk] = vmerged
            bchanged = True
    if not ocanon.get("lib_chapter") and oother.get("lib_chapter"):
        ocanon["lib_chapter"] = oother["lib_chapter"]
        bchanged = True
    if bchanged:
        smeta.SaveSourceMetaEntry(scanon, ocanon)
    smeta.SaveSourceMetaEntry(sother, None)


def MergeSourceNodes(omatch, n):
    """合并两个重复 source 节点的字段与元数据。"""
    scanon_id = omatch.get("id")
    sother_id = n.get("id")
    md.MergeWikiIntoNode(omatch, n, {"type": "source"})
    if scanon_id:
        omatch["id"] = scanon_id
    for sfield in ("aliases", "authors", "tags"):
        vmerged = list(dict.fromkeys((omatch.get(sfield) or []) + (n.get(sfield) or [])))
        if vmerged:
            omatch[sfield] = vmerged
    if n.get("ingested") or omatch.get("ingested"):
        omatch["ingested"] = True
    ore = dict(omatch.get("research") or {})
    nre = n.get("research") or {}
    if nre or ore:
        vrq = list(dict.fromkeys((ore.get("rq_links") or []) + (nre.get("rq_links") or [])))
        omatch["research"] = {**nre, **ore}
        if vrq:
            omatch["research"]["rq_links"] = vrq
    if not omatch.get("rawfile") and n.get("rawfile"):
        omatch["rawfile"] = n["rawfile"]
    if not omatch.get("url") and n.get("url"):
        omatch["url"] = n["url"]
    if not omatch.get("year") and n.get("year"):
        omatch["year"] = n["year"]
    if not omatch.get("summary") and n.get("summary"):
        omatch["summary"] = n["summary"]
    EnsureNodeRawfile(omatch)
    if sother_id and scanon_id and sother_id != scanon_id:
        valiases = list(dict.fromkeys((omatch.get("aliases") or []) + [sother_id]))
        omatch["aliases"] = valiases
        _MergeSourceMetaEntries(scanon_id, sother_id)


def _SameSource(a, b):
    """判断两个 source 节点是否指向同一篇文献。"""
    if a.get("id") == b.get("id"):
        return True
    sid_a = (a.get("id") or "").lower()
    sid_b = (b.get("id") or "").lower()
    if sid_a and sid_a == sid_b:
        return True
    if a.get("id") in (b.get("aliases") or []) or b.get("id") in (a.get("aliases") or []):
        return True
    rfa = a.get("rawfile") or ResolveRawfileForKey(a.get("id", ""))
    rfb = b.get("rawfile") or ResolveRawfileForKey(b.get("id", ""))
    if rfa and rfb and rfa == rfb:
        return True
    sdoi_a = _ExtractDoi(a)
    sdoi_b = _ExtractDoi(b)
    if sdoi_a and sdoi_a == sdoi_b:
        return True
    sta = _NormalizeTitle(a.get("title"))
    stb = _NormalizeTitle(b.get("title"))
    sya = str(a.get("year") or "").strip()
    syb = str(b.get("year") or "").strip()
    if sta and sta == stb and len(sta) >= 8:
        if sya and syb and sya == syb:
            return True
        if not sya and not syb:
            return True
    return False


def DedupeSourceNodes(vnodes):
    """合并重复 source 节点（同一 PDF / DOI / 标题年份 / 别名）。"""
    vothers = [n for n in vnodes if n.get("type") != "source"]
    vsources = [n for n in vnodes if n.get("type") == "source"]
    vsources.sort(key=lambda x: -_SourceCanonicalScore(x))
    vmerged = []
    for n in vsources:
        EnsureNodeRawfile(n)
        omatch = next((m for m in vmerged if _SameSource(n, m)), None)
        if omatch:
            MergeSourceNodes(omatch, n)
        else:
            vmerged.append(n)
    return vothers + vmerged


def SortAuthorKey(onode):
    """首作者或标题首字，供论文库排序。"""
    vauthors = onode.get("authors") or []
    if vauthors:
        sfirst = str(vauthors[0]).strip()
        if sfirst:
            return re.split(r"[\s,，、]+", sfirst)[0].lower()
    return (onode.get("title") or onode.get("id") or "").lower()


def SourceTimestamps(onode):
    """返回 (added_at, ingested_at) Unix 秒级时间戳。"""
    nadded = 0
    ningested = 0
    skey = onode.get("id", "")
    spath = smeta.FindSourcePagePath(skey)
    if onode.get("rawfile"):
        rpath = os.path.join(paths.rawsourcesdir, onode["rawfile"])
        if os.path.isfile(rpath):
            nadded = max(nadded, int(os.path.getmtime(rpath)))
    if spath and os.path.isfile(spath):
        nmt = int(os.path.getmtime(spath))
        nadded = max(nadded, nmt)
        if onode.get("ingested"):
            ningested = nmt
    return nadded, ningested


def EnrichSourceLibraryMeta(vnodes):
    """为 source 节点补充论文库分类阶段与自定义标签。"""
    for n in vnodes:
        EnsureNodeRawfile(n)
        spath = smeta.FindSourcePagePath(n.get("id", ""))
        if n.get("rawfile") or spath:
            n["type"] = "source"
            if spath:
                with open(spath, "r", encoding="utf-8") as f:
                    ofm, nbody = md.ParseFrontmatter(f.read())
                n["ingested"] = md.SourcePageIngested(ofm, nbody)
        if n.get("type") != "source":
            continue
        bdeep = HasDeepReportFile(n.get("id", ""))
        bstandard = HasStandardReportFile(n.get("id", ""))
        n["deep_done"] = bdeep
        n["standard_done"] = bstandard
        import analysis_version as aver
        aver.EnrichNodeStaleFlags(n, paths.wikidir)
        n["lib_stage"] = stage.ResolveLibStage(n.get("ingested"), bstandard, bdeep)
        n["lib_tags"] = smeta.GetLibTags(n.get("id", ""))
        n["lib_rq"] = smeta.GetLibRq(n.get("id", ""))
        n["lib_chapter"] = smeta.GetLibChapter(n.get("id", ""))
        n["suggested_tags"] = [str(t).strip() for t in (n.get("tags") or []) if str(t).strip()]
        vrqs = list((n.get("research") or {}).get("rq_links") or [])
        n["suggested_rq"] = [r for r in vrqs if r and r not in n["lib_rq"]]
        nadded, ningested = SourceTimestamps(n)
        n["added_at"] = nadded
        n["ingested_at"] = ningested
        n["lib_rank"] = stage.StageRank(n.get("lib_stage"))
        n["sort_author"] = SortAuthorKey(n)

