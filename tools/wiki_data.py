#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Wiki 数据 API：页面读取、日志、待纳入列表。"""

import json
import logging
import os
from datetime import datetime

import topic_manager as topics
import wiki_config as cfg
import wiki_paths as paths
import wiki_markdown as md
import wiki_source_meta as smeta
import wiki_scan as scan

logger = logging.getLogger(__name__)


def BuildData(bforce=False):
    import wiki_refresh as refresh
    return refresh.GetWikiData(bforce=bforce)


def PendingSources():
    """返回尚未摄入（无对应 wiki/sources/<key>.md）的原始文献文件名。"""
    import wiki_refresh as refresh
    omap = {n["id"]: n for n in refresh.GetWikiData()["nodes"]}
    vpending = []
    for fn in smeta.ListSources():
        key = md.ParseSourceFilename(fn)["key"]
        node = omap.get(key)
        if not node or not node.get("ingested"):
            vpending.append(fn)
    return vpending


def GetPageContent(sid):
    """按 id 读取 wiki 页面正文（供 /api/page 懒加载）。"""
    sid = (sid or "").strip()
    if not sid or ".." in sid or "/" in sid or "\\" in sid:
        return None
    spath = ResolveWikiPagePath(sid)
    if not spath:
        return None
    with open(spath, "r", encoding="utf-8") as f:
        ntext = f.read()
    ofm, nbody = md.ParseFrontmatter(ntext)
    stype = ofm.get("type", "unknown")
    stitle = ofm.get("title", sid)
    if stype == "analysis-report":
        try:
            import research_deep as rdeep
            sbody = rdeep.NormalizeReportBody(nbody, stitle)
        except Exception:
            sbody = nbody
    else:
        sbody = nbody
    return {
        "id": sid,
        "title": stitle,
        "type": stype,
        "body": sbody,
    }


def ResolveWikiPagePath(sid):
    """按 id 直接定位 wiki 页面路径（避免全量扫描）。"""
    sid = (sid or "").strip()
    if not sid or ".." in sid or "/" in sid or "\\" in sid:
        return None
    for stype, ocfg in cfg.typeconfig.items():
        sdir = ocfg.get("dir")
        if not sdir:
            continue
        spath = os.path.join(paths.wikidir, sdir, sid + ".md")
        if os.path.isfile(spath):
            return spath
    return None


def GenerateIndex():
    """根据当前扫描结果自动重写 wiki/index.md 与 overview（单次 ScanWiki）。"""
    import wiki_refresh as refresh
    try:
        refresh.RefreshWiki(bwrite_files=True)
    except Exception as e:
        logger.warning("RefreshWiki 失败：%s", e)


def AppendLog(nmessage):
    """向 wiki/log.md 追加一条带时间戳的审计记录。"""
    logpath = os.path.join(paths.wikidir, "log.md")
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    line = "- [%s] %s\n" % (stamp, nmessage)
    if os.path.isfile(logpath):
        with open(logpath, "a", encoding="utf-8") as f:
            f.write(line)
    else:
        with open(logpath, "w", encoding="utf-8") as f:
            f.write("---\ntype: log\ntitle: 操作审计日志\n---\n\n# Log · 操作历史\n\n" + line)
