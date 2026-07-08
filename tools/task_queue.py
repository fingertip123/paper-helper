#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统一任务队列进度 API（ingest / query / standard / deep）。"""
import job_state as jobs

_SKIP_INGEST = frozenset({"uid", "gen"})
_SKIP_QUERY = frozenset({"uid", "gen"})
_SKIP_PIPELINE = frozenset({"uid", "gen", "started_at"})


def _StripJob(ojob, vskip):
    if not isinstance(ojob, dict):
        return {}
    return {k: v for k, v in ojob.items() if k not in vskip}


def GetTaskProgress(skind, nuid=0):
    """返回单类任务的进度快照（供 /api/tasks/progress 与旧 progress 端点复用）。"""
    skind = (skind or "").strip().lower()
    if skind == "ingest":
        with jobs.ingestlock:
            return _StripJob(jobs.GetIngestJob(nuid), _SKIP_INGEST)
    if skind == "query":
        with jobs.querylock:
            return _StripJob(jobs.GetQueryJob(nuid), _SKIP_QUERY)
    if skind == "standard":
        return _StripJob(jobs.GetStandardJobStatus(nuid), _SKIP_PIPELINE)
    if skind == "deep":
        return _StripJob(jobs.GetDeepJobStatus(nuid), _SKIP_PIPELINE)
    return None


def GetAllTasksProgress(nuid=0):
    """返回全部流水线任务的进度字典。"""
    return {sk: GetTaskProgress(sk, nuid) for sk in jobs.TASK_KINDS}


def AnyTaskRunning(nuid=0):
    """是否有任一任务在运行。"""
    oall = GetAllTasksProgress(nuid)
    return any((o.get("running") for o in oall.values()))
