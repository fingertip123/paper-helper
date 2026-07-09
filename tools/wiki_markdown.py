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

# 结构化 / 已加引号的 YAML 标量起始字符：这些开头不需要（也不应）再补引号
_YAML_STRUCT_HEADS = set("[{\"'|>&*!#%@`?")
_FM_KV = re.compile(r"^(\s*)([\w\-.]+):[ \t]+(\S.*?)[ \t]*$")


def _NeedsQuote(sval):
    """判断一个裸标量值是否会破坏 YAML（最常见：值里含未转义的 ': '）。"""
    if not sval or sval[0] in _YAML_STRUCT_HEADS:
        return False
    return (": " in sval) or sval.endswith(":") or (" #" in sval)


def _RepairFrontmatterBlock(sblock):
    """给会破坏 YAML 的裸标量值补双引号（LLM 生成 title/desc 含冒号是高发错误）。"""
    vout = []
    for sline in sblock.splitlines():
        m = _FM_KV.match(sline)
        if m and _NeedsQuote(m.group(3)):
            sval = m.group(3).replace("\\", "\\\\").replace('"', '\\"')
            vout.append('%s%s: "%s"' % (m.group(1), m.group(2), sval))
        else:
            vout.append(sline)
    return "\n".join(vout)


def _UnquoteScalar(sval):
    sval = sval.strip()
    if len(sval) >= 2 and sval[0] == sval[-1] and sval[0] in ("'", '"'):
        return sval[1:-1]
    return sval


def _LenientParseBlock(sblock):
    """逐行宽松解析：只认顶层 key: value 与简单列表，绝不抛异常（最终兜底）。"""
    o = {}
    slistkey = None
    for sraw in sblock.splitlines():
        if not sraw.strip() or sraw.lstrip().startswith("#"):
            continue
        mli = re.match(r"^\s+-\s+(.*\S)\s*$", sraw)
        if mli and slistkey is not None and isinstance(o.get(slistkey), list):
            o[slistkey].append(_UnquoteScalar(mli.group(1)))
            continue
        m = re.match(r"^([\w\-.]+):\s*(.*)$", sraw)
        if not m:
            continue
        skey, sval = m.group(1), m.group(2).strip()
        if sval == "":
            o[skey] = []
            slistkey = skey
            continue
        slistkey = None
        if sval.startswith("[") and sval.endswith("]"):
            o[skey] = [_UnquoteScalar(x) for x in sval[1:-1].split(",") if x.strip()]
        else:
            o[skey] = _UnquoteScalar(sval)
    return o


def _SafeLoadFrontmatter(sblock):
    """尽最大努力把 frontmatter 解析为 dict：原样 → 补引号修复 → 逐行宽松。"""
    try:
        return yaml.safe_load(sblock)
    except yaml.YAMLError:
        pass
    try:
        return yaml.safe_load(_RepairFrontmatterBlock(sblock))
    except yaml.YAMLError:
        return _LenientParseBlock(sblock)


def ParseFrontmatter(ntext):
    """从 Markdown 文本中提取 YAML frontmatter（容错：坏 YAML 不再让整库崩溃）。"""
    omatch = frontmatterpattern.match(ntext)
    if not omatch:
        return {}, ntext
    sblock = omatch.group(1)
    nbody = ntext[omatch.end():]
    if yaml is None:
        raise ImportError("缺少 PyYAML 依赖，请执行：pip install PyYAML")
    oparsed = _SafeLoadFrontmatter(sblock)
    if not isinstance(oparsed, dict):
        # None / 列表 / 标量等异常形态：降级为无 frontmatter，保留正文，不中断扫描
        return {}, nbody
    return oparsed, nbody


def SanitizeFrontmatter(ntext):
    """写入前修正：若 frontmatter 非法，就地给问题标量补引号后返回（保持原有格式）。"""
    omatch = frontmatterpattern.match(ntext)
    if not omatch or yaml is None:
        return ntext
    sblock = omatch.group(1)
    try:
        yaml.safe_load(sblock)
        return ntext  # 已合法，原样返回
    except yaml.YAMLError:
        pass
    sfixed = _RepairFrontmatterBlock(sblock)
    return ntext[:omatch.start(1)] + sfixed + ntext[omatch.end(1):]


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
