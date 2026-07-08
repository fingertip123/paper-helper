#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""知识库问答后台任务。"""
import logging

import wiki_core as core
import wiki_ops as wops
import wiki_refresh as refresh
import request_log
from app_scope import UserScope
from llm_client import CallLlmStream
from job_state import GetQueryJob, QueryJobAlive, ReleaseLlm, TryAcquireLlm, querylock

logger = logging.getLogger(__name__)


def RunQueryJob(oconfig, squestion, bsave, sroot=None, nuid=0, ngen=0):
    """后台线程：知识库问答，不阻塞网页其他操作。文件读写阶段绑定提交者的数据根。"""
    logger.info("知识查询开始 uid=%s gen=%s rid=%s", nuid, ngen, request_log.CurrentId() or "-")
    if not TryAcquireLlm("query", squestion[:48], nuid):
        with querylock:
            if QueryJobAlive(nuid, ngen):
                ojob = GetQueryJob(nuid)
                ojob["running"] = False
                ojob["finished"] = True
                ojob["error"] = "大模型正忙，请稍后再试"
                ojob["status"] = "error"
        return
    try:
        with UserScope(sroot):
            wops.Init(core.wikidir, core.rawsourcesdir, core.rootdir)
            scontext = wops.CollectQueryContext(squestion)
        slang = oconfig.get("language", "中文")
        vmessages = [
            {"role": "system", "content": (
                "你是研栈知识库助手。仅根据提供的 wiki 页面作答；"
                "引用时写 [[page-id]]；不确定处标明待核实。"
                "用%s回答。" % slang
            )},
            {"role": "user", "content": "知识库摘录：\n%s\n\n问题：%s" % (scontext, squestion)},
        ]
        vparts = []

        def OnChunk(stext):
            vparts.append(stext)
            with querylock:
                if QueryJobAlive(nuid, ngen):
                    ojob = GetQueryJob(nuid)
                    ojob["answer"] = "".join(vparts)
                    ojob["status"] = "streaming"

        sanswer = CallLlmStream(oconfig, vmessages, fonchunk=OnChunk)
        if not sanswer:
            sanswer = "".join(vparts)
        osaved = None
        if bsave:
            with UserScope(sroot):
                wops.Init(core.wikidir, core.rawsourcesdir, core.rootdir)
                osaved = wops.SaveQueryPage(squestion, sanswer)
                refresh.RefreshWiki(bwrite_files=True, bforce=True)
                core.AppendLog("[query] %s → %s" % (squestion[:60], osaved.get("id")))
        with querylock:
            if QueryJobAlive(nuid, ngen):
                ojob = GetQueryJob(nuid)
                ojob["answer"] = sanswer
                ojob["saved"] = osaved
                ojob["error"] = ""
                ojob["status"] = "done"
    except Exception as e:
        logger.exception("知识查询失败 uid=%s gen=%s", nuid, ngen)
        with querylock:
            if QueryJobAlive(nuid, ngen):
                ojob = GetQueryJob(nuid)
                ojob["error"] = str(e)
                ojob["status"] = "error"
    finally:
        ReleaseLlm("query", nuid)
        with querylock:
            if QueryJobAlive(nuid, ngen):
                ojob = GetQueryJob(nuid)
                ojob["running"] = False
                ojob["finished"] = True
