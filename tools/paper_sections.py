#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""文献正文分段与智能节选（纳入 / 标准 / 深度分析共用）。"""
import re

_VHEADER_RULES = (
    ("abstract", (r"abstract", r"summary", r"摘要")),
    ("introduction", (r"introduction", r"background", r"literature review", r"引言", r"背景")),
    ("methods", (
        r"method", r"methodolog", r"identification", r"research design",
        r"data(?!set)", r"empirical strateg", r"方法", r"识别策略", r"研究设计", r"数据",
    )),
    ("results", (r"result", r"finding", r"empirical", r"结果", r"发现")),
    ("conclusion", (r"conclusion", r"discussion", r"concluding", r"结论", r"讨论")),
)

_VINGEST_ORDER = ("abstract", "methods", "results", "conclusion", "introduction")
_VDEEP_ORDER = ("abstract", "introduction", "methods", "results", "conclusion")


def _LineLooksLikeHeader(sline):
    sline = (sline or "").strip()
    if not sline or len(sline) > 120:
        return False
    if sline.startswith("#"):
        return True
    if re.match(r"^\d+(\.\d+)*[\.\)]?\s+\S", sline):
        return True
    if sline.isupper() and len(sline.split()) <= 8:
        return True
    if len(sline) <= 48 and _MatchSectionKey(sline):
        return True
    return False


def _MatchSectionKey(sline):
    slow = re.sub(r"^#+\s*", "", (sline or "").strip())
    slow = re.sub(r"^\d+(\.\d+)*[\.\)]?\s*", "", slow).strip().lower()
    if not slow:
        return ""
    for skey, vpatterns in _VHEADER_RULES:
        for spat in vpatterns:
            if re.search(spat, slow, re.I):
                return skey
    return ""


def SplitSections(stext):
    """按常见论文章节标题切分正文。"""
    stext = stext or ""
    oresult = {
        "full": stext,
        "abstract": "",
        "introduction": "",
        "methods": "",
        "results": "",
        "conclusion": "",
        "other": "",
    }
    if not stext.strip():
        return oresult

    vlines = stext.split("\n")
    vblocks = []
    scurkey = "other"
    vcur = []
    for sline in vlines:
        if _LineLooksLikeHeader(sline):
            skey = _MatchSectionKey(sline)
            if skey:
                if vcur:
                    vblocks.append((scurkey, "\n".join(vcur)))
                scurkey = skey
                vcur = [sline]
                continue
        vcur.append(sline)
    if vcur:
        vblocks.append((scurkey, "\n".join(vcur)))

    if len(vblocks) <= 1 and vblocks and vblocks[0][0] == "other":
        return oresult

    for skey, sblock in vblocks:
        sblock = sblock.strip()
        if not sblock:
            continue
        if skey in oresult and skey != "full":
            if oresult[skey]:
                oresult[skey] += "\n\n" + sblock
            else:
                oresult[skey] = sblock
        else:
            oresult["other"] += ("\n\n" if oresult["other"] else "") + sblock
    return oresult


def _PackSections(osections, vorder, nmax):
    if not stext_has_named_sections(osections):
        return (osections.get("full") or "")[:nmax]
    vparts = []
    nlen = 0
    for skey in vorder:
        sblock = (osections.get(skey) or "").strip()
        if not sblock:
            continue
        slabel = "## %s\n" % skey
        if nlen + len(slabel) + len(sblock) + 2 <= nmax:
            vparts.append(slabel + sblock)
            nlen += len(slabel) + len(sblock) + 2
            continue
        nremain = nmax - nlen - len(slabel) - 5
        if nremain > 300:
            vparts.append(slabel + sblock[:nremain] + "\n…")
        break
    if vparts:
        return "\n\n".join(vparts)
    return (osections.get("full") or "")[:nmax]


def stext_has_named_sections(osections):
    return any((osections.get(k) or "").strip() for k in _VINGEST_ORDER)


def PackForIngest(stext, nmax=14000):
    return _PackSections(SplitSections(stext), _VINGEST_ORDER, nmax)


def PackForDeep(stext, nmax=32000):
    return _PackSections(SplitSections(stext), _VDEEP_ORDER, nmax)
