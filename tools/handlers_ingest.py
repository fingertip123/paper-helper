#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""纳入研究 / 标准分析 / 深度分析。"""
import os
import threading

import app_context as actx
import research_deep as rdeep
import research_standard as rstd
import wiki_core as core
import request_log
from app_config import LoadConfig
from app_ingest import RunIngestJob
from io_utils import SafeName
from job_state import BeginIngestJob, GetIngestJob, LlmBusyPayload, ingestlock


class HandlerIngestMixin:

    def _ingest(self):
        body = self._body()
        oconfig = LoadConfig()
        nuid = self._Uid()
        with ingestlock:
            ojob = GetIngestJob(nuid)
            if ojob["running"]:
                return self._send(200, dict(ojob, status="running"))
        obusy = LlmBusyPayload(nuid)
        if obusy and obusy.get("busy") != "ingest":
            return self._send(200, self._MaybeOtherUserBusy(obusy))
        rawfile = body.get("rawfile")
        targets = [SafeName(rawfile)] if rawfile else core.PendingSources()
        if not targets:
            return self._send(200, {"status": "no_pending"})
        noauth = "pollinations.ai" in (oconfig.get("base_url") or "")
        if not HasUsableApiKey(oconfig) and not noauth:
            return self._send(200, {"status": "need_key", "pending": len(targets)})
        serr = self._CheckLlmQuota(len(targets))
        if serr:
            return self._send(200, {"status": "error", "error": serr})
        ouser = getattr(self, "_user", None)
        _, ngen = BeginIngestJob(
            nuid,
            running=True, total=len(targets), done=0, current="",
            ingested=[], failed=[], briefs=[], finished=False, cancelled=False,
        )
        threading.Thread(
            target=request_log.WrapTarget(RunIngestJob, request_log.CurrentId()),
            args=(oconfig, targets, ouser["root"] if ouser else None, nuid, ngen),
            daemon=True,
        ).start()
        return self._send(200, {"status": "started", "total": len(targets)})


    def _ingestcancel(self):
        nuid = self._Uid()
        with ingestlock:
            ojob = GetIngestJob(nuid)
            if not ojob.get("running"):
                return self._send(200, {"status": "idle", **{k: v for k, v in ojob.items()
                                                             if k not in ("uid", "gen")}})
            ojob["cancelled"] = True
            return self._send(200, {k: v for k, v in dict(ojob, status="cancelling").items()
                                    if k not in ("uid", "gen")})


    def _deep_analyze(self):
        """触发五阶段深度分析（须已纳入且保留原始 PDF）。"""
        oconfig = LoadConfig()
        body = self._body()
        sid = (body.get("id") or body.get("key") or "").strip()
        sfile = SafeName(body.get("rawfile") or "")
        if not sfile and sid:
            sfile = SafeName(core.ResolveRawfileForKey(sid))
        if sid and not core.FindSourcePagePath(sid):
            return self._send(400, {"error": "请先「纳入研究」后再进行深度分析"})
        if not sfile:
            return self._send(400, {"error": "找不到原始 PDF，深度研究需要 PDF 原文，请重新上传后再试"})
        spdf = os.path.join(core.rawsourcesdir, sfile)
        if not os.path.isfile(spdf):
            return self._send(400, {"error": "原始 PDF 不在文献库中，请重新上传后再进行深度分析"})
        noauth = "pollinations.ai" in (oconfig.get("base_url") or "")
        if not HasUsableApiKey(oconfig) and not noauth:
            return self._send(200, {"status": "need_key"})
        nuid = self._Uid()
        if rdeep.GetDeepJobStatus(nuid).get("running"):
            return self._send(200, {"error": "深度分析正在进行中，请等待完成"})
        obusy = LlmBusyPayload(nuid)
        if obusy and obusy.get("busy") != "deep":
            return self._send(200, self._MaybeOtherUserBusy(obusy))
        ouser = getattr(self, "_user", None)
        serr = self._CheckLlmQuota(5)
        if serr:
            return self._send(200, {"status": "error", "error": serr})
        oresult = rdeep.StartDeepAnalysis(
            oconfig, sfile, ouser["root"] if ouser else None, skey=sid or None, nuid=nuid)
        if "error" in oresult:
            return self._send(200, oresult)
        return self._send(200, {"status": "started", "file": sfile, "id": sid or ""})


    def _standard_analyze(self):
        """触发两阶段标准分析（须已纳入且保留原始 PDF）。"""
        oconfig = LoadConfig()
        body = self._body()
        sid = (body.get("id") or body.get("key") or "").strip()
        sfile = SafeName(body.get("rawfile") or "")
        if not sfile and sid:
            sfile = SafeName(core.ResolveRawfileForKey(sid))
        if sid and not core.FindSourcePagePath(sid):
            return self._send(400, {"error": "请先「纳入研究」后再进行标准分析"})
        if not sfile:
            return self._send(400, {"error": "找不到原始 PDF，标准分析需要 PDF 原文，请重新上传后再试"})
        spdf = os.path.join(core.rawsourcesdir, sfile)
        if not os.path.isfile(spdf):
            return self._send(400, {"error": "原始 PDF 不在文献库中，请重新上传后再进行标准分析"})
        noauth = "pollinations.ai" in (oconfig.get("base_url") or "")
        if not HasUsableApiKey(oconfig) and not noauth:
            return self._send(200, {"status": "need_key"})
        nuid = self._Uid()
        if rstd.GetStandardJobStatus(nuid).get("running"):
            return self._send(200, {"error": "标准分析正在进行中，请等待完成"})
        obusy = LlmBusyPayload(nuid)
        if obusy and obusy.get("busy") != "standard":
            return self._send(200, self._MaybeOtherUserBusy(obusy))
        ouser = getattr(self, "_user", None)
        serr = self._CheckLlmQuota(2)
        if serr:
            return self._send(200, {"status": "error", "error": serr})
        oresult = rstd.StartStandardAnalysis(
            oconfig, sfile, ouser["root"] if ouser else None, skey=sid or None, nuid=nuid)
        if "error" in oresult:
            return self._send(200, oresult)
        return self._send(200, {"status": "started", "file": sfile, "id": sid or ""})
