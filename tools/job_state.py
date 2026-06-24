#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LLM 任务互斥锁与 ingest/query 进度状态（按 uid 隔离）。"""
import threading

ingestlock = threading.RLock()
querylock = threading.RLock()
ingestjobs = {}
queryjobs = {}
ingest_active_uid = 0
query_active_uid = 0
llmrunlock = threading.Lock()
ollmstate = {"owner": "", "detail": ""}


def ResetJobDict(ojob, ngen, **fields):
    ojob.clear()
    ojob.update(fields)
    ojob["gen"] = ngen


def DefaultIngestJob(nuid=0):
    return {
        "running": False, "total": 0, "done": 0, "current": "",
        "ingested": [], "failed": [], "briefs": [], "finished": False,
        "cancelled": False, "uid": nuid, "gen": 0,
    }


def DefaultQueryJob(nuid=0):
    return {
        "running": False, "question": "", "answer": "", "error": "",
        "finished": False, "saved": None, "status": "idle", "uid": nuid, "gen": 0,
        "qid": "",
    }


def GetIngestJob(nuid=0):
    with ingestlock:
        if nuid not in ingestjobs:
            ingestjobs[nuid] = DefaultIngestJob(nuid)
        return ingestjobs[nuid]


def GetQueryJob(nuid=0):
    with querylock:
        if nuid not in queryjobs:
            queryjobs[nuid] = DefaultQueryJob(nuid)
        return queryjobs[nuid]


def BeginIngestJob(nuid, **fields):
    global ingest_active_uid
    with ingestlock:
        ojob = GetIngestJob(nuid)
        ngen = ojob.get("gen", 0) + 1
        ResetJobDict(ojob, ngen, uid=nuid, **fields)
        ingest_active_uid = nuid
        return ojob, ngen


def BeginQueryJob(nuid, **fields):
    global query_active_uid
    with querylock:
        ojob = GetQueryJob(nuid)
        ngen = ojob.get("gen", 0) + 1
        ResetJobDict(ojob, ngen, uid=nuid, **fields)
        query_active_uid = nuid
        return ojob, ngen


def IngestJobAlive(nuid, ngen):
    with ingestlock:
        return GetIngestJob(nuid).get("gen") == ngen


def QueryJobAlive(nuid, ngen):
    with querylock:
        return GetQueryJob(nuid).get("gen") == ngen


def IsIngestCancelled():
    with ingestlock:
        return bool(GetIngestJob(ingest_active_uid).get("cancelled"))


def TryAcquireLlm(sowner, sdetail=""):
    with llmrunlock:
        if ollmstate["owner"] and ollmstate["owner"] != sowner:
            return False
        ollmstate["owner"] = sowner
        ollmstate["detail"] = sdetail
        return True


def ReleaseLlm(sowner):
    with llmrunlock:
        if ollmstate["owner"] == sowner:
            ollmstate["owner"] = ""
            ollmstate["detail"] = ""


def LlmBusyPayload():
    with llmrunlock:
        sowner = ollmstate.get("owner") or ""
        sdetail = ollmstate.get("detail") or ""
    if not sowner:
        return None
    if sowner == "ingest":
        with ingestlock:
            ojob = GetIngestJob(ingest_active_uid)
            scur = ojob.get("current") or sdetail or "文献"
        sshort = scur if len(scur) <= 34 else scur[:33] + "…"
        return {
            "status": "busy", "busy": "ingest",
            "message": "正在纳入研究（%s），大模型暂无法同时处理其他任务，请稍后再试。" % sshort,
        }
    if sowner == "query":
        with querylock:
            ojob = GetQueryJob(query_active_uid)
            sq = ojob.get("question") or sdetail or "问题"
        sshort = sq if len(sq) <= 28 else sq[:27] + "…"
        return {
            "status": "busy", "busy": "query",
            "message": "知识查询进行中（「%s」），请稍后再纳入研究。" % sshort,
        }
    if sowner == "deep":
        import research_deep as rdeep
        ostatus = rdeep.GetDeepJobStatus(rdeep.GetDeepActiveUid())
        scur = ostatus.get("key") or ostatus.get("current") or sdetail or "文献"
        sshort = scur if len(scur) <= 34 else scur[:33] + "…"
        return {
            "status": "busy", "busy": "deep",
            "message": "深度分析进行中（%s），大模型暂无法同时处理其他任务，请稍后再试。" % sshort,
        }
    return {"status": "busy", "busy": sowner, "message": "大模型正在处理其他任务，请稍后再试。"}
