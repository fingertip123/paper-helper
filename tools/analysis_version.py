#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全项目 LLM 流水线版本管理：写入打标、读取比对、过期检测。"""
import os
import re
from datetime import datetime

from io_utils import FormatFrontmatter

# 每次升级对应流水线的 prompt / 阶段逻辑 / 输出结构时递增。
PIPELINE_VERSIONS = {
    "ingest": 2,
    "standard": 1,
    "deep": 2,
    "query": 1,
    "comparison": 1,
}

PIPELINE_LABELS = {
    "ingest": "纳入研究",
    "standard": "标准分析",
    "deep": "深度研究",
    "query": "知识查询",
    "comparison": "对比页",
}

# 向后兼容旧引用
DEEP_PIPELINE_VERSION = PIPELINE_VERSIONS["deep"]
STANDARD_PIPELINE_VERSION = PIPELINE_VERSIONS["standard"]
INGEST_PIPELINE_VERSION = PIPELINE_VERSIONS["ingest"]

_FM_HEAD_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_PIPELINE_RE = re.compile(r"^pipeline:\s*(\S+)\s*$", re.M)
_PIPELINE_VER_RE = re.compile(r"^pipeline_version:\s*(\d+)\s*$", re.M)

# ingest 一次写入的 wiki 子目录（不含 analysis / queries 等独立流水线产物）
_INGEST_WIKI_DIRS = (
    "sources/", "concepts/", "entities/", "research-questions/",
    "synthesis/", "experiments/",
)


def GetCurrentVersion(spipeline):
    return int(PIPELINE_VERSIONS.get(spipeline or "", 0))


def GetAllVersions():
    return dict(PIPELINE_VERSIONS)


def PipelineLabel(spipeline):
    return PIPELINE_LABELS.get(spipeline, spipeline or "未知")


def PipelineForWikiPath(srelpath):
    """根据 wiki 相对路径判断应使用的流水线类型。"""
    slow = (srelpath or "").replace("\\", "/").lower()
    for sprefix in _INGEST_WIKI_DIRS:
        if slow.startswith(sprefix) or ("/" + sprefix) in slow:
            return "ingest"
    if slow.startswith("analysis/"):
        if slow.endswith("-standard.md"):
            return "standard"
        if slow.endswith("-report.md"):
            return "deep"
    if slow.startswith("comparisons/"):
        return "comparison"
    if slow.startswith("queries/"):
        return "query"
    return ""


def ReadPageMeta(spath):
    """读取页面 frontmatter 中的 pipeline 元数据。"""
    if not spath or not os.path.isfile(spath):
        return None
    try:
        with open(spath, "r", encoding="utf-8") as f:
            shead = f.read(4096)
    except OSError:
        return None
    if not shead.startswith("---"):
        return {"pipeline": "", "pipeline_version": 0}
    oend = shead.find("\n---", 3)
    if oend < 0:
        return {"pipeline": "", "pipeline_version": 0}
    sfront = shead[3:oend]
    nver = 0
    skind = ""
    om = _PIPELINE_VER_RE.search(sfront)
    if om:
        nver = int(om.group(1))
    om = _PIPELINE_RE.search(sfront)
    if om:
        skind = om.group(1).strip()
    return {"pipeline": skind, "pipeline_version": nver}


ReadReportMeta = ReadPageMeta


def IsPageStale(spath, spipeline=None, ncurrent=None):
    """页面版本低于当前流水线版本时视为过期；无版本号视为 v0。"""
    ometa = ReadPageMeta(spath)
    if ometa is None:
        return False
    skind = spipeline or ometa.get("pipeline") or ""
    if not skind:
        return False
    ncurrent = ncurrent if ncurrent is not None else GetCurrentVersion(skind)
    if ometa.get("pipeline") and ometa["pipeline"] != skind:
        return True
    return int(ometa.get("pipeline_version") or 0) < int(ncurrent)


IsReportStale = IsPageStale


def _ParseSimpleFrontmatter(syaml):
    ofm = {}
    for sline in (syaml or "").split("\n"):
        if ":" not in sline:
            continue
        skey, _, sval = sline.partition(":")
        skey, sval = skey.strip(), sval.strip()
        if sval.startswith("[") and sval.endswith("]"):
            try:
                import json
                olist = json.loads(sval.replace("'", '"'))
                ofm[skey] = olist if isinstance(olist, list) else [str(olist)]
            except Exception:
                sinner = sval[1:-1].strip()
                ofm[skey] = [x.strip().strip('"').strip("'") for x in sinner.split(",") if x.strip()] if sinner else []
        elif sval in ("true", "True"):
            ofm[skey] = True
        elif sval in ("false", "False"):
            ofm[skey] = False
        elif len(sval) >= 2 and sval[0] == sval[-1] and sval[0] in ('"', "'"):
            ofm[skey] = sval[1:-1]
        else:
            ofm[skey] = sval
    return ofm


def StampMarkdown(scontent, spipeline, nversion=None):
    """在 Markdown 内容中写入/更新 pipeline 与 pipeline_version。"""
    nversion = nversion if nversion is not None else GetCurrentVersion(spipeline)
    scontent = scontent or ""
    om = _FM_HEAD_RE.match(scontent)
    if not om:
        ofm = {
            "type": "unknown",
            "pipeline": spipeline,
            "pipeline_version": nversion,
            "updated": datetime.now().strftime("%Y-%m-%d"),
        }
        return FormatFrontmatter(ofm, scontent)
    ofm = _ParseSimpleFrontmatter(om.group(1))
    ofm["pipeline"] = spipeline
    ofm["pipeline_version"] = nversion
    ofm["updated"] = datetime.now().strftime("%Y-%m-%d")
    return FormatFrontmatter(ofm, scontent[om.end():])


def FrontmatterPipelineLines(spipeline, nversion, **ofields):
    """生成含 pipeline 标记的 frontmatter 行（不含 --- 分隔符）。"""
    vlines = []
    for skey, sval in ofields.items():
        if isinstance(sval, list):
            import json
            vlines.append("%s: %s" % (skey, json.dumps(sval, ensure_ascii=False)))
        elif isinstance(sval, bool):
            vlines.append("%s: %s" % (skey, "true" if sval else "false"))
        else:
            vlines.append("%s: %s" % (skey, sval))
    vlines.append("pipeline: %s" % spipeline)
    vlines.append("pipeline_version: %d" % nversion)
    return vlines


def ReportFrontmatterFields(spipeline, nversion, stitle, ssourcekey, sstamp):
    """analysis-report 页 frontmatter 行。"""
    return FrontmatterPipelineLines(
        spipeline, nversion,
        type="analysis-report",
        title=stitle,
        sources=[ssourcekey],
        created=sstamp,
        updated=sstamp,
    )


def EnrichNodeStaleFlags(n, owikidir):
    """为 source 节点补充各流水线过期标记。"""
    skey = n.get("id") or ""
    n["ingest_stale"] = False
    n["standard_stale"] = False
    n["deep_stale"] = False
    n["stale_kinds"] = []
    if n.get("type") != "source":
        return
    spath = os.path.join(owikidir, "sources", skey + ".md")
    if n.get("ingested") and os.path.isfile(spath):
        if IsPageStale(spath, "ingest"):
            n["ingest_stale"] = True
            n["stale_kinds"].append("ingest")
    if n.get("standard_done"):
        spath = os.path.join(owikidir, "analysis", skey + "-standard.md")
        if IsPageStale(spath, "standard"):
            n["standard_stale"] = True
            n["stale_kinds"].append("standard")
    if n.get("deep_done"):
        spath = os.path.join(owikidir, "analysis", skey + "-report.md")
        if IsPageStale(spath, "deep"):
            n["deep_stale"] = True
            n["stale_kinds"].append("deep")
    n["pipeline_stale"] = bool(n["stale_kinds"])


def DetectStalePipelines(owikidir, vnodes=None):
    """扫描 wiki，返回所有过期流水线产物。"""
    vout = []
    if vnodes is None:
        import wiki_refresh as refresh
        vnodes = refresh.GetWikiData().get("nodes") or []

    for n in vnodes:
        if n.get("type") == "source" and n.get("ingested"):
            skey = n["id"]
            stitle = n.get("title") or skey
            spath = os.path.join(owikidir, "sources", skey + ".md")
            if IsPageStale(spath, "ingest"):
                vout.append({"id": skey, "kind": "ingest", "title": stitle, "label": PipelineLabel("ingest")})
            if n.get("standard_done"):
                spath = os.path.join(owikidir, "analysis", skey + "-standard.md")
                if IsPageStale(spath, "standard"):
                    vout.append({"id": skey, "kind": "standard", "title": stitle, "label": PipelineLabel("standard")})
            if n.get("deep_done"):
                spath = os.path.join(owikidir, "analysis", skey + "-report.md")
                if IsPageStale(spath, "deep"):
                    vout.append({"id": skey, "kind": "deep", "title": stitle, "label": PipelineLabel("deep")})

    for n in vnodes:
        if n.get("type") != "query":
            continue
        spath = _NodePath(owikidir, n)
        if spath and IsPageStale(spath, "query"):
            vout.append({
                "id": n["id"], "kind": "query",
                "title": n.get("title") or n["id"],
                "label": PipelineLabel("query"),
            })

    for n in vnodes:
        if n.get("type") != "comparison":
            continue
        spath = _NodePath(owikidir, n)
        if not spath:
            continue
        ometa = ReadPageMeta(spath)
        skind = ometa.get("pipeline") or "comparison"
        if IsPageStale(spath, skind):
            vout.append({
                "id": n["id"], "kind": skind,
                "title": n.get("title") or n["id"],
                "label": PipelineLabel(skind),
            })
    return vout


DetectStaleAnalysis = DetectStalePipelines


def _NodePath(owikidir, n):
    """根据节点 type/id 推断 wiki 文件路径。"""
    sid = n.get("id") or ""
    stype = n.get("type") or ""
    if not sid:
        return ""
    ocfg = {
        "source": ("sources", ".md"),
        "concept": ("concepts", ".md"),
        "entity": ("entities", ".md"),
        "rq": ("research-questions", ".md"),
        "comparison": ("comparisons", ".md"),
        "synthesis": ("synthesis", ".md"),
        "query": ("queries", ".md"),
        "analysis-report": ("analysis", ".md"),
        "experiment": ("experiments", ".md"),
    }
    if stype not in ocfg:
        return ""
    sdir, sext = ocfg[stype]
    spath = os.path.join(owikidir, sdir, sid + sext)
    return spath if os.path.isfile(spath) else ""
