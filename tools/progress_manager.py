#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""研究进度看板：章节、任务、审阅管理。数据存储在 <选题>/progress.json。"""
import os
import json
import re
from datetime import datetime

import topic_manager as topics


def ProgressPath(ntopicid=None):
    return os.path.join(topics.GetTopicDir(ntopicid), "progress.json")


def _Now():
    return datetime.now().strftime("%Y-%m-%d")


def _NewTaskId(vtasks):
    nmax = 0
    for ot in vtasks:
        sid = ot.get("id", "")
        if sid.startswith("t") and sid[1:].isdigit():
            nmax = max(nmax, int(sid[1:]))
    return "t%d" % (nmax + 1)


def _ExtractChaptersFromPurpose(spurpose):
    """从 purpose.md 的「论文章节规划」段落提取章节名，生成初始骨架。"""
    vchaps = []
    if not spurpose:
        return vchaps
    # 尝试匹配 "## 5. 论文章节规划" 之后到下一个 ## 之间的内容
    om = re.search(r"## 5\. 论文章节规划.*?\n\n(.+?)(?=\n## |\Z)", spurpose, re.DOTALL)
    if not om:
        return vchaps
    sbody = om.group(1).strip()
    # 按行解析：每行如果以 - 开头或编号开头，作为章节名
    nid = 1
    for sline in sbody.split("\n"):
        sline = sline.strip()
        if not sline:
            continue
        # 去掉 Markdown checkbox：- [ ] 或 - [x]
        sline = re.sub(r"^-\s*\[.*?\]\s*", "", sline).strip()
        # 去掉其他可能的编号前缀
        stitle = re.sub(r"^[\d]+[\.\、\)\s]+", "", sline).strip()
        if not stitle or len(stitle) < 2:
            continue
        vchaps.append({
            "id": "ch-%d" % nid,
            "title": stitle,
            "status": "todo",
            "target_words": 0,
            "current_words": 0,
            "planned_start": "",
            "planned_due": "",
            "actual_done": "",
            "linked_sources": [],
            "linked_concepts": [],
            "linked_rq": [],
            "notes": "",
            "tasks": [],
        })
        nid += 1
    return vchaps


def _AutoInitIfNeeded(ntopicid, odata):
    """如果 progress.json 不存在，从 purpose.md 提取章节规划生成初始数据。"""
    if odata is not None and odata.get("chapters"):
        return odata
    spurpose = topics.ReadText(topics.RulePath("purpose.md", ntopicid))
    vchaps = _ExtractChaptersFromPurpose(spurpose)
    # 也提取里程碑作为截止时间参考
    sms = ""
    om = re.search(r"## 6\. 关键里程碑.*?\n\n(.+?)(?=\n## |\Z)", spurpose, re.DOTALL)
    if om:
        sms = om.group(1).strip()
    return {
        "updated": _Now(),
        "chapters": vchaps,
        "milestones_raw": sms,
        "review_rounds": [],
        "writing_stats": {
            "total_words": sum(c.get("current_words", 0) for c in vchaps),
            "target_words": sum(c.get("target_words", 0) for c in vchaps),
            "last_synced": "",
        },
    }


def LoadProgress(ntopicid=None):
    """读取进度数据，首次无文件时自动从 purpose 生成骨架。"""
    spath = ProgressPath(ntopicid)
    if os.path.isfile(spath):
        with open(spath, "r", encoding="utf-8") as f:
            odata = json.load(f)
    else:
        odata = None
    odata = _AutoInitIfNeeded(ntopicid, odata)
    # 确保每章有 tasks 字段
    for och in odata.get("chapters", []):
        if "tasks" not in och:
            och["tasks"] = []
    return odata


def SaveProgress(ntopicid, odata):
    odata["updated"] = _Now()
    spath = ProgressPath(ntopicid)
    os.makedirs(os.path.dirname(spath), exist_ok=True)
    with open(spath, "w", encoding="utf-8") as f:
        json.dump(odata, f, ensure_ascii=False, indent=2)


def AddChapter(ntopicid, stitle, ntarget_words=0):
    odata = LoadProgress(ntopicid)
    vchaps = odata.get("chapters", [])
    nmax = 0
    for och in vchaps:
        sid = och.get("id", "")
        if sid.startswith("ch-") and sid[3:].isdigit():
            nmax = max(nmax, int(sid[3:]))
    nchid = "ch-%d" % (nmax + 1)
    ochap = {
        "id": nchid,
        "title": stitle,
        "status": "todo",
        "target_words": ntarget_words,
        "current_words": 0,
        "planned_start": "",
        "planned_due": "",
        "actual_done": "",
        "linked_sources": [],
        "linked_concepts": [],
        "linked_rq": [],
        "notes": "",
        "tasks": [],
    }
    vchaps.append(ochap)
    SaveProgress(ntopicid, odata)
    return ochap


def UpdateChapter(ntopicid, nchid, opatch):
    odata = LoadProgress(ntopicid)
    for och in odata.get("chapters", []):
        if och.get("id") == nchid:
            # 如果是标记完成，自动填充日期
            if opatch.get("status") == "done" and not och.get("actual_done"):
                opatch["actual_done"] = _Now()
            och.update(opatch)
            break
    RecalcStats(odata)
    SaveProgress(ntopicid, odata)
    for och in odata.get("chapters", []):
        if och.get("id") == nchid:
            return och
    return None


def DeleteChapter(ntopicid, nchid):
    odata = LoadProgress(ntopicid)
    odata["chapters"] = [c for c in odata.get("chapters", []) if c.get("id") != nchid]
    RecalcStats(odata)
    SaveProgress(ntopicid, odata)
    return odata


def ReorderChapters(ntopicid, vids):
    odata = LoadProgress(ntopicid)
    omap = {c.get("id"): c for c in odata.get("chapters", [])}
    vnew = [omap[sid] for sid in vids if sid in omap]
    vnew += [c for c in odata.get("chapters", []) if c.get("id") not in vids]
    odata["chapters"] = vnew
    SaveProgress(ntopicid, odata)
    return odata


def AddTask(ntopicid, nchid, stitle):
    odata = LoadProgress(ntopicid)
    for och in odata.get("chapters", []):
        if och.get("id") == nchid:
            vtasks = och.get("tasks", [])
            vtasks.append({
                "id": _NewTaskId(vtasks),
                "title": stitle,
                "done": False,
            })
            och["tasks"] = vtasks
            break
    SaveProgress(ntopicid, odata)
    for och in odata.get("chapters", []):
        if och.get("id") == nchid:
            return och
    return None


def UpdateTask(ntopicid, nchid, ntaskid, opatch):
    odata = LoadProgress(ntopicid)
    for och in odata.get("chapters", []):
        if och.get("id") == nchid:
            for otask in och.get("tasks", []):
                if otask.get("id") == ntaskid:
                    otask.update(opatch)
                    break
            break
    SaveProgress(ntopicid, odata)
    for och in odata.get("chapters", []):
        if och.get("id") == nchid:
            return och
    return None


def DeleteTask(ntopicid, nchid, ntaskid):
    odata = LoadProgress(ntopicid)
    for och in odata.get("chapters", []):
        if och.get("id") == nchid:
            och["tasks"] = [t for t in och.get("tasks", []) if t.get("id") != ntaskid]
            break
    SaveProgress(ntopicid, odata)
    return odata


def SyncWordCount(ntopicid):
    """扫描 docs/ 下关联的 docx，更新各章节字数统计。"""
    odata = LoadProgress(ntopicid)
    ndocsdir = os.path.join(topics.GetTopicDir(ntopicid), "docs")
    # 尝试按章节 id 匹配 docs 下的同名子目录
    for och in odata.get("chapters", []):
        nchid = och.get("id", "")
        ndocdir = os.path.join(ndocsdir, nchid)
        nwords = 0
        if os.path.isdir(ndocdir):
            for sname in os.listdir(ndocdir):
                if sname.endswith(".docx"):
                    try:
                        import docx
                        odoc = docx.Document(os.path.join(ndocdir, sname))
                        for opara in odoc.paragraphs:
                            nwords += len(opara.text.replace(" ", ""))
                    except Exception:
                        pass
        och["current_words"] = nwords
    RecalcStats(odata)
    odata["writing_stats"]["last_synced"] = _Now()
    SaveProgress(ntopicid, odata)
    return odata


def RecalcStats(odata):
    vchaps = odata.get("chapters", [])
    odata["writing_stats"] = odata.get("writing_stats", {})
    odata["writing_stats"]["total_words"] = sum(c.get("current_words", 0) for c in vchaps)
    odata["writing_stats"]["target_words"] = sum(c.get("target_words", 0) for c in vchaps)


def ComputeCoverage(ntopicid):
    """返回各章节的文献/RQ 覆盖数据。"""
    odata = LoadProgress(ntopicid)
    vchaps = odata.get("chapters", [])
    # 统计所有已连接的 wiki 页面
    vused_src = set()
    vused_rq = set()
    for och in vchaps:
        for ss in och.get("linked_sources", []):
            vused_src.add(ss)
        for sr in och.get("linked_rq", []):
            vused_rq.add(sr)
    return {
        "chapters": vchaps,
        "linked_sources": sorted(vused_src),
        "linked_rq": sorted(vused_rq),
        "total_sources": len(vused_src),
        "total_rq_linked": len(vused_rq),
    }


def AddReviewRound(ntopicid, sreviewer, vchapter_ids, snotes=""):
    odata = LoadProgress(ntopicid)
    vrounds = odata.get("review_rounds", [])
    nrid = "r%d" % (len(vrounds) + 1)
    oround = {
        "id": nrid,
        "date": _Now(),
        "reviewer": sreviewer,
        "chapter_ids": vchapter_ids,
        "commment_file": "",
        "notes": snotes,
        "status": "pending",
    }
    vrounds.append(oround)
    odata["review_rounds"] = vrounds
    SaveProgress(ntopicid, odata)
    return oround


def UpdateReviewRound(ntopicid, nrid, opatch):
    odata = LoadProgress(ntopicid)
    for oround in odata.get("review_rounds", []):
        if oround.get("id") == nrid:
            oround.update(opatch)
            break
    SaveProgress(ntopicid, odata)
    return odata
