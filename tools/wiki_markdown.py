#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Markdown / frontmatter / wikilink 解析。"""

import json
import re

try:
    import yaml
except ImportError:
    yaml = None

import wiki_config as cfg

wikilinkpattern = cfg.wikilinkpattern
frontmatterpattern = cfg.frontmatterpattern
explicitrelmap = cfg.explicitrelmap
explicitrelpattern = cfg.explicitrelpattern

def ParseFrontmatter(ntext):
    """从 Markdown 文本中提取 YAML frontmatter。"""
    omatch = frontmatterpattern.match(ntext)
    if not omatch:
        return {}, ntext
    sblock = omatch.group(1)
    if yaml is None:
        raise ImportError("缺少 PyYAML 依赖，请执行：pip install PyYAML")
    try:
        oparsed = yaml.safe_load(sblock)
    except yaml.YAMLError as e:
        raise ValueError(
            "frontmatter YAML 解析失败，请检查格式（缩进、引号、嵌套值）：%s" % e
        ) from e
    if oparsed is None:
        return {}, ntext[omatch.end():]
    if not isinstance(oparsed, dict):
        raise ValueError("frontmatter 须为 YAML 映射（key: value），当前类型：%s" % type(oparsed).__name__)
    return oparsed, ntext[omatch.end():]


def SourcePageIngested(ofm, nbody=""):
    """判断 source 页是否已完成 LLM 纳入（排除 BibTeX 占位页）。"""
    if ofm.get("ingested") is False:
        return False
    vtags = ofm.get("tags") or []
    if isinstance(vtags, str):
        vtags = [vtags]
    if "BibTeX导入" in vtags:
        return False
    if "由 BibTeX 导入，待补充 PDF 并纳入研究" in (nbody or ""):
        return False
    return True


def IsSourceKeyIngested(skey):
    """检查 source key 是否已真实纳入研究。"""
    import wiki_source_meta as smeta
    spath = smeta.FindSourcePagePath(skey)
    if not spath:
        return False
    with open(spath, "r", encoding="utf-8") as f:
        ntext = f.read()
    ofm, nbody = ParseFrontmatter(ntext)
    return SourcePageIngested(ofm, nbody)


def ExtractLinks(nbody):
    """提取正文中的 [[wikilink]] 目标（去重）。"""
    vtargets = []
    for m in wikilinkpattern.finditer(nbody):
        target = m.group(1).strip()
        if target and target not in vtargets:
            vtargets.append(target)
    return vtargets


def FilenameToKey(sname):
    """把文件名转为稳定 kebab key（用于无「作者,年份,标题」格式时）。"""
    sslug = re.sub(r"[^\w\u4e00-\u9fff]+", "-", sname, flags=re.UNICODE).strip("-").lower()
    return sslug[:56] if sslug else "source"


def ParseSourceFilename(nfilename):
    """从原始 PDF 文件名解析出 作者 / 年份 / 标题 / 引用key。"""
    name = re.sub(r"\.(pdf|md|txt|docx)$", "", nfilename, flags=re.IGNORECASE)
    author, year, title = "", "", name
    m = re.match(r"^(.*?),\s*(\d{4})\s*,\s*(.*)$", name)
    if m:
        author, year, title = m.group(1).strip(), m.group(2), m.group(3).strip()
    else:
        m = re.match(r"^(.*?)\s*-\s*(\d{4})\s*-\s*(.*)$", name)
        if m:
            author, year, title = m.group(1).strip(), m.group(2), m.group(3).strip()
    firstword = re.split(r"[\s,]+", author)[0].lower() if author else ""
    if year and firstword:
        skey = firstword + "-" + year
    else:
        skey = FilenameToKey(name)
    return {"key": skey, "author": author, "year": year, "title": title, "filename": nfilename}


def MergeWikiIntoNode(existing, onode, ofm, nbody=""):
    """合并 wiki 页到已有节点，避免有 raw 文件的文献被降级为 unknown 而从论文库消失。"""
    for skey, sval in onode.items():
        if not sval:
            continue
        if skey == "type" and sval == "unknown" and existing.get("type") == "source":
            continue
        existing[skey] = sval
    if existing.get("rawfile"):
        existing["type"] = "source"
    if ofm.get("type") == "source" and SourcePageIngested(ofm, nbody):
        existing["ingested"] = True


def BuildNodeIndex(vnodes):
    """构造 别名/标题/文件名 -> 节点id 的解析表，用于 wikilink 匹配。"""
    omap = {}
    for node in vnodes:
        for c in [node["id"], node.get("title", "")] + node.get("aliases", []):
            if c:
                omap[c.strip().lower()] = node["id"]
    return omap


def InferEdgeType(stype, ttype):
    """根据源/目标节点 type 推断边语义类型。"""
    stype = stype or "unknown"
    ttype = ttype or "unknown"
    if stype == ttype:
        return "同类关联"
    omap = {
        ("source", "concept"): "引用概念",
        ("source", "entity"): "提及实体",
        ("source", "rq"): "关联问题",
        ("source", "source"): "文献对照",
        ("source", "comparison"): "纳入对比",
        ("source", "experiment"): "方法参考",
        ("source", "synthesis"): "综合引用",
        ("source", "analysis-report"): "深度报告",
        ("source", "query"): "探讨概念",
        ("concept", "rq"): "支撑问题",
        ("concept", "entity"): "概念-实体",
        ("concept", "source"): "引用概念",
        ("entity", "source"): "提及实体",
        ("rq", "concept"): "支撑问题",
        ("rq", "source"): "关联问题",
        ("purpose", "rq"): "研究目标",
        ("purpose", "concept"): "核心概念",
        ("comparison", "source"): "对比文献",
        ("comparison", "concept"): "引用概念",
        ("synthesis", "source"): "综合文献",
        ("synthesis", "concept"): "引用概念",
        ("query", "concept"): "探讨概念",
        ("query", "source"): "引用概念",
        ("experiment", "source"): "方法参考",
        ("analysis-report", "source"): "深度报告",
    }
    return omap.get((stype, ttype), "链接")


def ParseRelEndpoint(spart):
    """解析显式关系行中的节点端点（wikilink 或 plain id）。"""
    spart = (spart or "").strip()
    omatch = re.match(r"\[\[([^\]|]+)", spart)
    if omatch:
        return omatch.group(1).strip()
    return spart.strip()


def ExtractExplicitRelations(nbody):
    """从 comparison/synthesis 等页正文提取显式 typed 关系行。"""
    vout = []
    for omatch in explicitrelpattern.finditer(nbody or ""):
        srel = omatch.group(1).lower()
        ssrc = ParseRelEndpoint(omatch.group(2))
        stgt = ParseRelEndpoint(omatch.group(3))
        if not ssrc or not stgt:
            continue
        vout.append({
            "source": ssrc,
            "target": stgt,
            "type": explicitrelmap.get(srel, "链接"),
            "note": (omatch.group(4) or "").strip(),
        })
    return vout


def RefreshEdgeMeta(vnodes, vedges):
    """去重/enrich 后按最终节点 type 同步边的 src_type、tgt_type 与推断 type。"""
    onodetype = {n["id"]: n.get("type", "unknown") for n in vnodes}
    vids = set(onodetype)
    vout = []
    for e in vedges:
        srcid, tgtid = e["source"], e["target"]
        if srcid not in vids or tgtid not in vids:
            continue
        stype = onodetype[srcid]
        ttype = onodetype[tgtid]
        if e.get("explicit"):
            vetype = e.get("type") or InferEdgeType(stype, ttype)
        else:
            vetype = InferEdgeType(stype, ttype)
        vout.append({
            "source": srcid,
            "target": tgtid,
            "type": vetype,
            "src_type": stype,
            "tgt_type": ttype,
            "explicit": bool(e.get("explicit")),
        })
    return vout


def ComputePageRank(vnodes, vedges, ndamp=0.85, niters=40):
    """轻量 PageRank，用于图谱节点重要度着色/半径。"""
    vids = [n["id"] for n in vnodes if n.get("type") != "purpose"]
    if not vids:
        return {}
    ncount = len(vids)
    oidx = {sid: i for i, sid in enumerate(vids)}
    oout = {i: [] for i in range(ncount)}
    for e in vedges:
        si, ti = oidx.get(e["source"]), oidx.get(e["target"])
        if si is None or ti is None or si == ti:
            continue
        oout[si].append(ti)
        oout[ti].append(si)
    vr = [1.0 / ncount] * ncount
    nbase = (1.0 - ndamp) / ncount
    for _ in range(niters):
        vnew = [nbase] * ncount
        for i in range(ncount):
            if not oout[i]:
                continue
            nshare = ndamp * vr[i] / len(oout[i])
            for j in oout[i]:
                vnew[j] += nshare
        vr = vnew
    nmax = max(vr) if vr else 1.0
    return {vids[i]: (vr[i] / nmax if nmax else 0.0) for i in range(ncount)}


def ExtractMarkdownSections(nbody):
    """按 ## 标题切分正文段落。"""
    osections = {}
    scurrent = ""
    vbuf = []
    for line in nbody.split("\n"):
        if line.startswith("## "):
            if scurrent:
                osections[scurrent] = "\n".join(vbuf).strip()
            scurrent = line[3:].strip()
            vbuf = []
        elif scurrent:
            vbuf.append(line)
    if scurrent:
        osections[scurrent] = "\n".join(vbuf).strip()
    return osections


def StripWikiMarkup(stext):
    """去掉 wikilink 与简单 Markdown 标记，便于摘要展示。"""
    stext = re.sub(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]", lambda m: m.group(2) or m.group(1), stext)
    return re.sub(r"[*_`]", "", stext).strip()


def ExtractSourceResearch(nbody):
    """从 source 页固定章节提取研究化字段，供前端展示。"""
    osec = ExtractMarkdownSections(nbody)
    srelation = osec.get("与本论文的关系", "")
    stension = osec.get("与已有文献的张力", "") or osec.get("共识与张力", "")
    snext = osec.get("下一步阅读建议", "") or osec.get("下一步", "")
    vrq = []
    for ssec in ("关联研究问题", "与本论文的关系"):
        for m in wikilinkpattern.finditer(osec.get(ssec, "")):
            tid = m.group(1).strip()
            if tid not in vrq:
                vrq.append(tid)
    return {
        "relation": StripWikiMarkup(srelation)[:420] if srelation else "",
        "tensions": StripWikiMarkup(stension)[:320] if stension else "",
        "design": StripWikiMarkup(osec.get("可借鉴的研究设计", ""))[:320],
        "limits": StripWikiMarkup(osec.get("局限与存疑", ""))[:320],
        "next_steps": StripWikiMarkup(snext)[:320] if snext else "",
        "rq_links": vrq,
        "has_research": bool(srelation or stension or snext),
    }


def GetSummary(nbody):
    """优先取「一句话概括」，否则取正文首段。"""
    osec = ExtractMarkdownSections(nbody)
    if osec.get("一句话概括"):
        s = StripWikiMarkup(osec["一句话概括"].split("\n")[0])
        if s:
            return s[:160]
    for line in nbody.split("\n"):
        s = line.strip()
        if not s or s.startswith(("#", ">", "|", "---")):
            continue
        return StripWikiMarkup(s)[:160]
    return ""
