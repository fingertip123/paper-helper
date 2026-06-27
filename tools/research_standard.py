#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""两阶段标准文献分析（介于「纳入研究」与「深度研究」之间）。"""
import os
import re
import json
import time
import logging
import threading

import wiki_core as core
import topic_manager as topics
import wiki_workflow as wflow
from io_utils import SafeName
from paper_io import ExtractPaperText
from paper_sections import PackForDeep
from llm_client import CallLlm, ParseLlmJson, IngestCancelled
from job_state import ResetJobDict, ReleaseLlm, TryAcquireLlm, LlmBusyPayload

logger = logging.getLogger(__name__)

standardlock = threading.RLock()
standardjobs = {}
standard_active_uid = 0
_standard_run_uid = 0
_standard_run_gen = 0
STANDARD_TIMEOUT_SEC = 900

PDF_MISSING_MSG = "找不到原始 PDF 文件。标准分析需要 PDF 原文，请重新上传后再试。"
NOT_INGESTED_MSG = "该文献尚未「纳入研究」，请先纳入后再进行标准分析。"


def DefaultStandardJob(nuid=0):
    return {
        "running": False, "finished": False, "progress": 0, "stage": "准备",
        "current": "", "key": "", "error": "", "result": None,
        "cancelled": False, "uid": nuid, "gen": 0, "started_at": 0,
    }


def GetStandardJob(nuid=0):
    with standardlock:
        if nuid not in standardjobs:
            standardjobs[nuid] = DefaultStandardJob(nuid)
        return standardjobs[nuid]


def StandardJobAlive(nuid, ngen):
    with standardlock:
        return GetStandardJob(nuid).get("gen") == ngen


def GetStandardActiveUid():
    with standardlock:
        return standard_active_uid


def BeginStandardJob(nuid, **fields):
    global standard_active_uid, _standard_run_uid, _standard_run_gen
    with standardlock:
        ojob = GetStandardJob(nuid)
        ngen = ojob.get("gen", 0) + 1
        ResetJobDict(
            ojob, ngen, uid=nuid, started_at=time.time(),
            running=True, finished=False, progress=0, stage="准备",
            error="", result=None, cancelled=False, **fields,
        )
        standard_active_uid = nuid
        _standard_run_uid = nuid
        _standard_run_gen = ngen
        return ngen


def GetStandardJobStatus(nuid=0):
    with standardlock:
        return dict(GetStandardJob(nuid))


def IsStandardCancelled():
    with standardlock:
        ojob = GetStandardJob(standard_active_uid)
        if ojob.get("cancelled"):
            return True
        nstart = ojob.get("started_at") or 0
    return nstart > 0 and (time.time() - nstart) > STANDARD_TIMEOUT_SEC


def _Now():
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d")


def _ReadSourcePage(skey):
    spath = os.path.join(core.wikidir, "sources", skey + ".md")
    if os.path.isfile(spath):
        with open(spath, "r", encoding="utf-8") as f:
            return f.read()
    return ""


def _ResolvePdfPath(nfilename, skey=None):
    sfile = SafeName(nfilename or "")
    if not sfile and skey:
        sfile = SafeName(core.ResolveRawfileForKey(skey))
    if not sfile:
        raise FileNotFoundError(PDF_MISSING_MSG)
    fullpath = os.path.join(core.rawsourcesdir, sfile)
    if not os.path.isfile(fullpath):
        raise FileNotFoundError(PDF_MISSING_MSG)
    return fullpath, sfile


def _ReadPurposeRqs():
    sp = topics.ReadText(topics.RulePath("purpose.md"))
    ofields = topics.ParsePurposeFields(sp or "")
    vrqlines = []
    for skey in ("rq1", "rq2", "rq3", "rq4"):
        sval = (ofields.get(skey) or "").strip()
        if sval and sval not in ("（待填写）", "（未填写）"):
            vrqlines.append(sval)
    sthesis = (ofields.get("thesis") or "").strip()[:1200]
    return "\n".join(vrqlines) if vrqlines else "（尚未填写具体研究问题）", sthesis


def _LlmJson(oconfig, system, user, nmaxuser=10000):
    content = CallLlm(oconfig, [
        {"role": "system", "content": system},
        {"role": "user", "content": user[:nmaxuser] if len(user) > nmaxuser else user},
    ], bjson=True, fcancel=IsStandardCancelled)
    return ParseLlmJson(content) if isinstance(content, str) else content


def _LoadPriorSources():
    import wiki_refresh as refresh
    vnodes = refresh.GetWikiData()["nodes"]
    vsources = [n for n in vnodes if n.get("type") == "source" and n.get("ingested")]
    return "\n".join(
        "- [[%s]]: %s" % (n["id"], n.get("summary", "")[:100])
        for n in vsources[:15]
    )


def _Stage1Method(oconfig, spacked, skey, stitle, ssourcepage):
    system = (
        "你是社科论文方法论分析助手。从正文中提取识别策略、变量与主要结果，输出 JSON。"
        "纳入阶段已有精简摘要，请勿重复，专注方法与识别。"
    )
    user = (
        "## 论文\n标题：%s\nkey：%s\n\n## 已纳入 wiki 摘要\n%s\n\n"
        "## 正文节选\n%s\n\n"
        "输出 JSON：identification_strategy, data_description, key_variables[], "
        "main_results[], design_strengths[], design_limits[], methodology_summary（3–5 句）。"
        % (stitle, skey, (ssourcepage or "")[:2500], spacked)
    )
    return _LlmJson(oconfig, system, user, 28000)


def _Stage2RqDraft(oconfig, skey, stitle, omethod, srqctx, sthesis, sprior):
    system = (
        "你是研究问题对齐专家。基于 purpose 中的 RQ 与用户论点，"
        "论证级评估本篇文献关联，并起草跨文献对比要点。输出 JSON。"
    )
    user = (
        "## 论文：%s（%s）\n\n## 方法论要点\n%s\n\n"
        "## 研究问题\n%s\n\n## 当前论点\n%s\n\n## 库内已纳入文献\n%s\n\n"
        "输出 JSON：rq_alignment[{rq,alignment,reason}], thesis_implication, "
        "challenges_thesis[], comparison_draft（3–6 句，须含 [[wikilink]]）, "
        "standard_summary（4–6 句，供写入 source 页）。"
        % (stitle, skey, json.dumps(omethod, ensure_ascii=False)[:8000],
           srqctx, sthesis or "（未填写）", sprior or "（无）")
    )
    return _LlmJson(oconfig, system, user)


def _AppendStandardSummaryToSource(skey, ssummary):
    spath = os.path.join(core.wikidir, "sources", skey + ".md")
    if not os.path.isfile(spath) or not (ssummary or "").strip():
        return
    with open(spath, "r", encoding="utf-8") as f:
        ntext = f.read()
    ssection = "## 标准分析摘要\n\n" + ssummary.strip() + "\n"
    if "## 标准分析摘要" in ntext:
        ntext = re.sub(
            r"\n## 标准分析摘要\n[\s\S]*?(?=\n## |\Z)",
            "\n" + ssection,
            ntext,
            count=1,
        )
    else:
        ntext = ntext.rstrip() + "\n\n" + ssection
    with open(spath, "w", encoding="utf-8") as f:
        f.write(ntext)


def _WriteStandardReport(skey, stitle, omethod, orq):
    spath = os.path.join(core.wikidir, "analysis", skey + "-standard.md")
    os.makedirs(os.path.dirname(spath), exist_ok=True)
    import analysis_version as aver
    stamp = _Now()
    vlines = ["---"]
    vlines.extend(aver.ReportFrontmatterFields(
        "standard", aver.GetCurrentVersion("standard"),
        "标准分析报告 — %s" % stitle, skey, stamp,
    ))
    vlines.append("tags: [标准分析]")
    vlines.append("---")
    vlines += [
        "",
        "# 标准分析报告：%s" % stitle,
        "",
        "> 原始文献：[[%s]]；深度审计请使用「深度研究」。" % skey,
        "",
        "## 方法论摘要",
        "",
        (omethod.get("methodology_summary") or "（待补充）").strip(),
        "",
        "## 识别策略",
        "",
        (omethod.get("identification_strategy") or "（待补充）").strip(),
        "",
        "## RQ 对齐",
        "",
    ]
    for item in (orq.get("rq_alignment") or []):
        vlines.append("- **%s**（%s）：%s" % (
            item.get("rq") or "?",
            item.get("alignment") or "?",
            (item.get("reason") or "")[:200],
        ))
    vlines += [
        "",
        "## 与论点的关系",
        "",
        (orq.get("thesis_implication") or "（待补充）").strip(),
        "",
        "## 对比草稿",
        "",
        (orq.get("comparison_draft") or "（待补充）").strip(),
        "",
    ]
    with open(spath, "w", encoding="utf-8") as f:
        f.write("\n".join(vlines) + "\n")
    return os.path.relpath(spath, core.rootdir)


def _WriteComparisonDraft(skey, stitle, orq):
    import analysis_version as aver
    from io_utils import FormatFrontmatter
    comp_id = "%s-draft" % skey
    spath = os.path.join(core.wikidir, "comparisons", comp_id + ".md")
    os.makedirs(os.path.dirname(spath), exist_ok=True)
    stamp = _Now()
    ofm = {
        "type": "comparison",
        "title": "对比草稿 — %s" % stitle,
        "sources": [skey],
        "tags": ["标准分析", "草稿"],
        "created": stamp,
        "updated": stamp,
        "pipeline": "standard",
        "pipeline_version": aver.GetCurrentVersion("standard"),
    }
    nbody = (
        "# 对比草稿：%s\n\n"
        "> 由标准分析自动生成，完整对撞见深度研究后的 [[%s-cross]]。\n\n"
        "## 要点\n\n"
        "%s\n"
    ) % (stitle, skey, (orq.get("comparison_draft") or "（待补充）").strip())
    with open(spath, "w", encoding="utf-8") as f:
        f.write(FormatFrontmatter(ofm, nbody))
    return os.path.relpath(spath, core.rootdir)


def StandardAnalyzePaper(oconfig, nfilename, sroot=None, skey=None):
    import app as appmod

    _DefaultUpdateCb(8, "准备")
    with appmod.UserScope(sroot):
        fullpath, sfile = _ResolvePdfPath(nfilename, skey)
        meta = core.ParseSourceFilename(sfile)
        rkey = skey or meta["key"]
        stitle = meta.get("title") or rkey
        ssourcepage = _ReadSourcePage(rkey)
        if not ssourcepage:
            raise ValueError(NOT_INGESTED_MSG)
        stext = ExtractPaperText(fullpath)
        srqctx, sthesis = _ReadPurposeRqs()
        sprior = _LoadPriorSources()
    if not stext.strip():
        raise ValueError(
            "无法从 PDF 提取文本（可能是扫描版）。"
            "可安装 pymupdf+pytesseract 后重试，或换可搜索 PDF。"
        )

    spacked = PackForDeep(stext)
    _DefaultUpdateCb(25, "阶段① 方法论")
    omethod = _Stage1Method(oconfig, spacked, rkey, stitle, ssourcepage)

    _DefaultUpdateCb(60, "阶段② RQ 对齐")
    orq = _Stage2RqDraft(oconfig, rkey, stitle, omethod, srqctx, sthesis, sprior)

    _DefaultUpdateCb(88, "写入报告")
    ssummary = (orq.get("standard_summary") or "").strip()
    if ssummary:
        ssummary += "\n\n完整报告：[[%s-standard]]" % rkey
    else:
        ssummary = "完整报告：[[%s-standard]]" % rkey

    with appmod.UserScope(sroot):
        srel = _WriteStandardReport(rkey, stitle, omethod, orq)
        scomp = _WriteComparisonDraft(rkey, stitle, orq)
        _AppendStandardSummaryToSource(rkey, ssummary)
        wflow.Init(core.wikidir)
        wflow.SyncRqPages(rkey, {"rq_links": [
            (x.get("rq") or "").strip()
            for x in (orq.get("rq_alignment") or [])
            if (x.get("rq") or "").strip()
        ]}, (orq.get("standard_summary") or "")[:120])
        core.AppendLog("[standard] %s：标准分析完成（%s；%s）" % (rkey, srel, scomp))
        import wiki_refresh as refresh
        refresh.RefreshWiki(bwrite_files=True, bforce=True)

    _DefaultUpdateCb(100, "完成")
    return {"key": rkey, "file": sfile, "report": srel, "draft": scomp, "title": stitle}


def _DefaultUpdateCb(npct, sstage=""):
    with standardlock:
        if not StandardJobAlive(_standard_run_uid, _standard_run_gen):
            return
        ojob = GetStandardJob(_standard_run_uid)
        ojob["progress"] = npct
        if sstage:
            ojob["stage"] = sstage


def _RunStandardJob(oconfig, nfilename, sroot=None, skey=None, nuid=0, ngen=0):
    global _standard_run_uid, _standard_run_gen
    try:
        oresult = StandardAnalyzePaper(oconfig, nfilename or "", sroot=sroot, skey=skey)
        with standardlock:
            if StandardJobAlive(nuid, ngen):
                ojob = GetStandardJob(nuid)
                ojob["result"] = oresult
                ojob["finished"] = True
                ojob["progress"] = 100
                ojob["error"] = ""
    except IngestCancelled as e:
        with standardlock:
            if StandardJobAlive(nuid, ngen):
                ojob = GetStandardJob(nuid)
                nstart = ojob.get("started_at") or 0
                btimeout = nstart > 0 and (time.time() - nstart) > STANDARD_TIMEOUT_SEC
                ojob["error"] = (
                    "标准分析已超时（%d 分钟）" % (STANDARD_TIMEOUT_SEC // 60) if btimeout
                    else (str(e).strip() or "已取消")
                )
                ojob["finished"] = True
                ojob["progress"] = -1
    except Exception as e:
        logger.exception("标准分析失败 uid=%s gen=%s key=%s", nuid, ngen, skey)
        with standardlock:
            if StandardJobAlive(nuid, ngen):
                ojob = GetStandardJob(nuid)
                ojob["error"] = str(e)
                ojob["finished"] = True
                ojob["progress"] = -1
    finally:
        ReleaseLlm("standard")
        with standardlock:
            if StandardJobAlive(nuid, ngen):
                GetStandardJob(nuid)["running"] = False


def StartStandardAnalysis(oconfig, nfilename, sroot=None, skey=None, nuid=0):
    with standardlock:
        if GetStandardJob(nuid).get("running"):
            return {"error": "标准分析正在进行中，请等待完成"}
    if not TryAcquireLlm("standard", skey or nfilename or ""):
        return LlmBusyPayload() or {"error": "大模型正忙，请稍后再试"}
    ngen = BeginStandardJob(
        nuid,
        current=nfilename or skey or "",
        key=skey or "",
    )
    t = threading.Thread(
        target=_RunStandardJob,
        args=(oconfig, nfilename, sroot),
        kwargs={"skey": skey, "nuid": nuid, "ngen": ngen},
        daemon=True,
    )
    t.start()
    return {"status": "started", "file": nfilename or skey or ""}
