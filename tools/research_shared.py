#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""深度 / 标准文献分析共享工具（消除 research_deep ↔ research_standard 重复）。"""
import os
import time
import logging
import threading

import wiki_core as core
import topic_manager as topics
from io_utils import SafeName
from llm_client import CallLlm, ParseLlmJson, IngestCancelled

logger = logging.getLogger(__name__)


def Now():
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d")


def ReadSourcePage(skey):
    spath = os.path.join(core.wikidir, "sources", skey + ".md")
    if os.path.isfile(spath):
        with open(spath, "r", encoding="utf-8") as f:
            return f.read()
    return ""


def ReadPurposeRqs():
    sp = topics.ReadText(topics.RulePath("purpose.md"))
    ofields = topics.ParsePurposeFields(sp or "")
    vrqlines = []
    for skey in ("rq1", "rq2", "rq3", "rq4"):
        sval = (ofields.get(skey) or "").strip()
        if sval and sval not in ("（待填写）", "（未填写）"):
            vrqlines.append(sval)
    sthesis = (ofields.get("thesis") or "").strip()[:1200]
    return "\n".join(vrqlines) if vrqlines else "（尚未填写具体研究问题）", sthesis


def PdfMissingMsg(smode):
    return "找不到原始 PDF 文件。%s需要 PDF 原文，请重新上传后再试。" % smode


def NotIngestedMsg(saction):
    return "该文献尚未「纳入研究」，请先纳入后再进行%s。" % saction


def ResolvePdfPath(nfilename, skey=None, spdf_missing_msg=""):
    sfile = SafeName(nfilename or "")
    if not sfile and skey:
        sfile = SafeName(core.ResolveRawfileForKey(skey))
    if not sfile:
        raise FileNotFoundError(spdf_missing_msg)
    fullpath = os.path.join(core.rawsourcesdir, sfile)
    if not os.path.isfile(fullpath):
        raise FileNotFoundError(spdf_missing_msg)
    return fullpath, sfile


def LlmJson(oconfig, system, user, nmaxuser=8000, fcancel=None):
    content = CallLlm(oconfig, [
        {"role": "system", "content": system},
        {"role": "user", "content": user[:nmaxuser] if len(user) > nmaxuser else user},
    ], bjson=True, fcancel=fcancel)
    return ParseLlmJson(content) if isinstance(content, str) else content


def LlmText(oconfig, system, user, nmaxuser=12000, fcancel=None):
    return CallLlm(oconfig, [
        {"role": "system", "content": system},
        {"role": "user", "content": user[:nmaxuser] if len(user) > nmaxuser else user},
    ], bjson=False, fcancel=fcancel)


def RunAnalysisJob(
    fanalyze,
    oconfig,
    nfilename,
    sroot=None,
    skey=None,
    nuid=0,
    ngen=0,
    *,
    slabel,
    ntimeout_sec,
    olock,
    fjob_alive,
    fget_job,
    skind,
    fbefore=None,
):
    """后台线程：执行分析任务；LLM 互斥锁由 StartAnalysisJob 获取，此处负责释放。"""
    if fbefore:
        fbefore()
    try:
        oresult = fanalyze(oconfig, nfilename or "", sroot=sroot, skey=skey)
        with olock:
            if fjob_alive(nuid, ngen):
                ojob = fget_job(nuid)
                ojob["result"] = oresult
                ojob["finished"] = True
                ojob["progress"] = 100
                ojob["error"] = ""
    except IngestCancelled as e:
        with olock:
            if fjob_alive(nuid, ngen):
                ojob = fget_job(nuid)
                nstart = ojob.get("started_at") or 0
                btimeout = nstart > 0 and (time.time() - nstart) > ntimeout_sec
                ojob["error"] = (
                    "%s已超时（%d 分钟）" % (slabel, ntimeout_sec // 60) if btimeout
                    else (str(e).strip() or "已取消")
                )
                ojob["finished"] = True
                ojob["progress"] = -1
    except Exception as e:
        logger.exception("%s失败 uid=%s gen=%s key=%s", slabel, nuid, ngen, skey)
        with olock:
            if fjob_alive(nuid, ngen):
                ojob = fget_job(nuid)
                ojob["error"] = str(e)
                ojob["finished"] = True
                ojob["progress"] = -1
    finally:
        from job_state import ReleaseLlm
        ReleaseLlm(skind, nuid)
        with olock:
            if fjob_alive(nuid, ngen):
                fget_job(nuid)["running"] = False


def StartAnalysisJob(
    oconfig,
    nfilename,
    sroot=None,
    skey=None,
    nuid=0,
    *,
    skind,
    sbusy_msg,
    fanalyze,
    frun_job,
    olock,
    fget_job,
    fbegin_job,
):
    """启动分析任务；与「纳入研究 / 知识查询」共用同一把 LLM 互斥锁。"""
    from job_state import TryAcquireLlm, LlmBusyPayload

    with olock:
        if fget_job(nuid).get("running"):
            return {"error": sbusy_msg}
    if not TryAcquireLlm(skind, skey or nfilename or "", nuid):
        return LlmBusyPayload(nuid) or {"error": "大模型正忙，请稍后再试"}
    ngen = fbegin_job(
        nuid,
        current=nfilename or skey or "",
        key=skey or "",
    )
    t = threading.Thread(
        target=frun_job,
        args=(oconfig, nfilename, sroot),
        kwargs={"skey": skey, "nuid": nuid, "ngen": ngen},
        daemon=True,
    )
    t.start()
    return {"status": "started", "file": nfilename or skey or ""}
