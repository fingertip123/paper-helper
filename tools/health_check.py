#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""服务健康检查（P2）。"""
import os
from datetime import datetime

import wiki_paths as paths
import wiki_refresh as refresh
import task_queue
import llm_client as llm


def RunHealthCheck(nuid=0, oconfig=None):
    """返回磁盘、wiki、LLM、任务队列快照。"""
    swiki = paths.wikidir or ""
    sraw = paths.rawsourcesdir or ""
    bwiki_ok = os.path.isdir(swiki) and os.access(swiki, os.W_OK)
    braw_ok = os.path.isdir(sraw) and os.access(sraw, os.W_OK)
    blm_ok = bool(oconfig and llm.HasUsableApiKey(oconfig))

    ostats = {"nodes": 0, "edges": 0}
    olint = {}
    try:
        odata = refresh.GetWikiData()
        ostats["nodes"] = len(odata.get("nodes") or [])
        ostats["edges"] = len(odata.get("edges") or [])
        olint = odata.get("lint") or {}
    except Exception:
        pass

    vissues = []
    if not bwiki_ok:
        vissues.append("wiki_dir")
    if not braw_ok:
        vissues.append("raw_dir")
    if not blm_ok:
        vissues.append("llm_key")

    return {
        "status": "ok" if not vissues else "degraded",
        "issues": vissues,
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "wiki": {
            "dir": swiki,
            "writable": bwiki_ok,
            "nodes": ostats["nodes"],
            "edges": ostats["edges"],
            "lint_orphans": olint.get("orphans", 0),
            "lint_stale": olint.get("stale_pipelines", 0),
        },
        "llm": {"configured": blm_ok},
        "tasks": task_queue.GetAllTasksProgress(nuid),
    }
