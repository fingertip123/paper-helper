#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""BibTeX 解析与导入（兼容 Zotero 导出）。"""
import os
import re
from datetime import datetime

import io_utils


def _CleanBibValue(sval):
    sval = (sval or "").strip()
    if len(sval) >= 2 and sval[0] == "{" and sval[-1] == "}":
        sval = sval[1:-1]
    elif len(sval) >= 2 and sval[0] == '"' and sval[-1] == '"':
        sval = sval[1:-1]
    sval = re.sub(r"\s+", " ", sval)
    return sval.strip()


def ParseBibtexEntries(stext):
    """解析 BibTeX 为条目列表。"""
    ventries = []
    if not (stext or "").strip():
        return ventries
    vchunks = re.split(r"\n(?=@)", stext.strip())
    for schunk in vchunks:
        schunk = schunk.strip()
        if not schunk.startswith("@"):
            continue
        ohead = re.match(r"@(\w+)\s*\{\s*([^,\s]+)\s*,", schunk, re.I | re.S)
        if not ohead:
            continue
        stype = ohead.group(1).lower()
        scitekey = ohead.group(2).strip()
        sbody = schunk[ohead.end():]
        ofields = {}
        for om in re.finditer(
            r"(\w+)\s*=\s*(\{(?:[^{}]|\{[^{}]*\})*\}|\"(?:\\.|[^\"])*\")",
            sbody,
            re.I | re.S,
        ):
            ofields[om.group(1).lower()] = _CleanBibValue(om.group(2))
        ofields["_type"] = stype
        ofields["_citekey"] = scitekey
        ventries.append(ofields)
    return ventries


def FirstAuthorSurname(sauthor):
    sauthor = (sauthor or "").strip()
    if not sauthor:
        return "unknown"
    spart = re.split(r"\s+and\s+", sauthor, flags=re.I)[0].strip()
    if "," in spart:
        return re.sub(r"[^\w\-]", "", spart.split(",")[0]).lower() or "unknown"
    vparts = spart.split()
    return re.sub(r"[^\w\-]", "", vparts[-1]).lower() if vparts else "unknown"


def SuggestSourceKey(ofields, oused=None):
    oused = oused or set()
    syear = re.sub(r"[^\d]", "", (ofields.get("year") or "")[:4])
    syear = syear[:4] if syear else "nd"
    sbase = "%s-%s" % (FirstAuthorSurname(ofields.get("author", "")), syear)
    sbase = re.sub(r"[^\w\-]", "-", sbase).strip("-") or "unknown-nd"
    skey = sbase
    nseq = 2
    while skey in oused:
        skey = "%s-%d" % (sbase, nseq)
        nseq += 1
    oused.add(skey)
    return skey


def ParseAuthors(sauthor):
    if not sauthor:
        return []
    vout = []
    for spart in re.split(r"\s+and\s+", sauthor, flags=re.I):
        spart = spart.strip()
        if spart:
            vout.append(spart)
    return vout


def ResolveDoiUrl(ofields):
    surl = (ofields.get("url") or "").strip()
    sdoi = (ofields.get("doi") or "").strip()
    if sdoi and not surl:
        return "https://doi.org/" + sdoi.lstrip("https://doi.org/")
    if surl.startswith("10."):
        return "https://doi.org/" + surl
    return surl


def FormatCitationText(skey, stitle, vauthors, syear):
    sname = "Unknown"
    if vauthors:
        sp = vauthors[0]
        if "," in sp:
            sname = sp.split(",")[0].strip()
        else:
            vparts = sp.split()
            sname = vparts[-1] if vparts else sname
        if len(vauthors) > 1:
            sname += " et al."
    sy = syear or "n.d."
    return "(%s, %s) [[%s]]" % (sname, sy, skey)


def ImportBibtex(stext, owikidir, orawdir=None, bcreate_placeholder=True):
    """导入 BibTeX：更新已有 source 元数据，可选创建占位 source 页。"""
    import wiki_core as core

    ventries = ParseBibtexEntries(stext)
    vupdated = []
    vcreated = []
    vskipped = []
    oused = set()
    os.makedirs(os.path.join(owikidir, "sources"), exist_ok=True)

    for ofields in ventries:
        scitekey = (ofields.get("_citekey") or "").strip()
        stitle = ofields.get("title") or scitekey or "Untitled"
        syear = re.sub(r"[^\d]", "", (ofields.get("year") or "")[:4])
        vauthors = ParseAuthors(ofields.get("author", ""))
        svenue = ofields.get("journal") or ofields.get("booktitle") or ofields.get("publisher") or ""
        surl = ResolveDoiUrl(ofields)

        skey = scitekey if re.match(r"^[\w\-]+$", scitekey or "") else ""
        if not skey:
            skey = SuggestSourceKey(ofields, oused)
        else:
            oused.add(skey)

        spath = os.path.join(owikidir, "sources", skey + ".md")
        stamp = datetime.now().strftime("%Y-%m-%d")

        if os.path.isfile(spath):
            with open(spath, "r", encoding="utf-8") as f:
                nfull = f.read()
            ofm, nbody = core.ParseFrontmatter(nfull)
            if stitle:
                ofm["title"] = stitle
            if syear:
                ofm["year"] = syear
            if vauthors:
                ofm["authors"] = vauthors
            if svenue:
                ofm["venue"] = svenue
            if surl:
                ofm["url"] = surl
            ofm["updated"] = stamp
            vfm = []
            for k, v in ofm.items():
                if isinstance(v, list):
                    vfm.append("%s: [%s]" % (k, ", ".join(str(x) for x in v)))
                else:
                    vfm.append("%s: %s" % (k, v))
            io_utils.AtomicWriteText(spath, "---\n" + "\n".join(vfm) + "\n---\n\n" + nbody.lstrip())
            vupdated.append(skey)
        elif bcreate_placeholder:
            sfront = (
                "---\n"
                "type: source\n"
                "title: %s\n"
                "authors: [%s]\n"
                "year: %s\n"
                "venue: %s\n"
                "url: %s\n"
                "sources: [%s]\n"
                "tags: [BibTeX导入]\n"
                "created: %s\n"
                "updated: %s\n"
                "---\n\n"
                "# %s\n\n"
                "## 一句话概括\n\n"
                "（由 BibTeX 导入，待补充 PDF 并纳入研究。）\n\n"
                "## 研究问题\n\n（待填写）\n\n"
                "## 方法与数据\n\n（待填写）\n\n"
                "## 主要结论\n\n（待填写）\n\n"
                "## 关联研究问题\n\n（待填写）\n"
            ) % (
                stitle,
                ", ".join(vauthors),
                syear or "",
                svenue,
                surl,
                skey,
                stamp,
                stamp,
                stitle,
            )
            io_utils.AtomicWriteText(spath, sfront)
            vcreated.append(skey)
        else:
            vskipped.append(scitekey or skey)

    return {
        "total": len(ventries),
        "updated": vupdated,
        "created": vcreated,
        "skipped": vskipped,
    }


def ListCitations(odata):
    """返回可插入 Word 的引用列表。"""
    vout = []
    for n in odata.get("nodes") or []:
        if n.get("type") != "source":
            continue
        vauthors = n.get("authors") or []
        if isinstance(vauthors, str):
            vauthors = [vauthors]
        syear = n.get("year") or ""
        stitle = n.get("title") or n["id"]
        vout.append({
            "id": n["id"],
            "title": stitle,
            "authors": vauthors,
            "year": syear,
            "ingested": bool(n.get("ingested")),
            "cite": FormatCitationText(n["id"], stitle, vauthors, syear),
        })
    vout.sort(key=lambda x: x["id"])
    return vout
