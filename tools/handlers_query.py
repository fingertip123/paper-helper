#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""知识库问答。"""
import threading
import uuid

import app_context as actx
from app_config import LoadConfig
from app_query import RunQueryJob
from job_state import BeginQueryJob, GetQueryJob, LlmBusyPayload, querylock
from llm_client import HasUsableApiKey
import request_log


class HandlerQueryMixin:

    def _query(self):
        body = self._body()
        squestion = (body.get("question") or "").strip()
        if not squestion:
            return self._send(400, {"error": "请输入问题"})
        oconfig = LoadConfig()
        noauth = "pollinations.ai" in (oconfig.get("base_url") or "")
        if not HasUsableApiKey(oconfig) and not noauth:
            return self._send(200, {"status": "need_key"})
        nuid = self._Uid()
        with querylock:
            ojob = GetQueryJob(nuid)
            if ojob.get("running"):
                if ojob.get("question") == squestion:
                    return self._send(200, dict(ojob, status="running"))
                return self._send(200, {
                    "status": "busy", "busy": "query",
                    "message": "上一条问答仍在进行，请稍后再提问。",
                })
        obusy = LlmBusyPayload(self._Uid())
        if obusy and obusy.get("busy") != "query":
            return self._send(200, self._MaybeOtherUserBusy(obusy))
        serr = self._CheckLlmQuota(1)
        if serr:
            return self._send(200, {"status": "error", "error": serr})
        bsave = body.get("save", True)
        ouser = getattr(self, "_user", None)
        sqid = uuid.uuid4().hex
        _, ngen = BeginQueryJob(
            nuid,
            running=True, question=squestion, answer="", error="",
            finished=False, saved=None, status="running", qid=sqid,
        )
        threading.Thread(
            target=request_log.WrapTarget(RunQueryJob, request_log.CurrentId()),
            args=(oconfig, squestion, bsave, ouser["root"] if ouser else None, nuid, ngen),
            daemon=True,
        ).start()
        return self._send(200, {"status": "started", "question": squestion, "qid": sqid})
