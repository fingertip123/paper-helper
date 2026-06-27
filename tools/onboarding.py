#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""引导式入门：欢迎向导 + 第一周任务清单进度。"""
import os
import json
from datetime import datetime

import topic_manager as topics

vplaceholders = ("（待填写）", "（未填写）", "")


def OnboardingPath():
    return os.path.join(topics.ConfigDir(), "onboarding.json")


def LoadOnboarding():
    spath = OnboardingPath()
    if not os.path.isfile(spath):
        return {}
    try:
        with open(spath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def SaveOnboarding(odata):
    os.makedirs(topics.ConfigDir(), exist_ok=True)
    with open(OnboardingPath(), "w", encoding="utf-8") as f:
        json.dump(odata, f, ensure_ascii=False, indent=2)


def IsPlaceholder(sval):
    sval = (sval or "").strip()
    return not sval or sval in vplaceholders


def GetChecklistProgress():
    """统计第一周任务完成度。"""
    import wiki_core as core

    nraw = len(core.ListSources())
    import wiki_refresh as refresh
    vnodes = refresh.GetWikiData()["nodes"]
    ningested = sum(
        1 for n in vnodes
        if n.get("type") == "source" and n.get("ingested")
    )
    ofields = topics.ParsePurposeFields(topics.ReadText(topics.RulePath("purpose.md")))
    hasrq = not IsPlaceholder(ofields.get("rq1"))

    return {
        "add_papers": {
            "key": "add_papers",
            "label": "添加 3 篇文献",
            "hint": "点击「添加文献」上传 PDF 或 Word",
            "action": "add_paper",
            "current": nraw,
            "target": 3,
            "done": nraw >= 3,
        },
        "analyze_paper": {
            "key": "analyze_paper",
            "label": "纳入研究 1 篇文献",
            "hint": "选中文献后点「纳入研究」，生成摘要、RQ 关联与综述备忘",
            "action": "analyze",
            "current": min(ningested, 1),
            "target": 1,
            "done": ningested >= 1,
        },
        "write_rq": {
            "key": "write_rq",
            "label": "明确第 1 个研究问题",
            "hint": "在「研究规则」中填写 RQ1",
            "action": "rules",
            "current": 1 if hasrq else 0,
            "target": 1,
            "done": hasrq,
        },
    }


def AllChecklistDone(ochecklist):
    return all(v.get("done") for v in ochecklist.values())


def NeedsWelcome():
    """是否弹出欢迎向导（仅填选题名即可开始）。"""
    ostate = LoadOnboarding()
    if ostate.get("welcome_done"):
        return False

    import wiki_core as core

    ofields = topics.ParsePurposeFields(topics.ReadText(topics.RulePath("purpose.md")))
    stitle = (ofields.get("working_title") or "").strip()
    # 已有真实题目且已添加文献 → 视为老用户，不再弹欢迎页
    if not IsPlaceholder(stitle) and len(core.ListSources()) > 0:
        ostate["welcome_done"] = True
        SaveOnboarding(ostate)
        return False
    return True


def ShowChecklist():
    ostate = LoadOnboarding()
    if ostate.get("checklist_dismissed"):
        return False
    if not ostate.get("welcome_done") and NeedsWelcome():
        return False
    ochecklist = GetChecklistProgress()
    return not AllChecklistDone(ochecklist)


def GetState():
    ochecklist = GetChecklistProgress()
    ball = AllChecklistDone(ochecklist)
    bwelcome = NeedsWelcome()
    return {
        "needs_welcome": bwelcome,
        "show_checklist": ShowChecklist(),
        "checklist": list(ochecklist.values()),
        "all_done": ball,
        "welcome_done": LoadOnboarding().get("welcome_done", False),
    }


def SetupFromTitle(stitle):
    """只填选题名：生成 purpose 初稿 + 研究问题占位页。"""
    import wiki_core as core

    stitle = (stitle or "").strip()
    if not stitle:
        raise ValueError("请填写论文题目")

    ofields = {k: "" for k, _, _ in topics.purposefields}
    ofields["working_title"] = stitle
    ofields["direction"] = stitle
    topics.SaveRule("purpose", ofields=ofields)

    stamp = datetime.now().strftime("%Y-%m-%d")
    srqdir = os.path.join(core.wikidir, "research-questions")
    srqpath = os.path.join(srqdir, "rq-main.md")
    if not os.path.isfile(srqpath):
        os.makedirs(srqdir, exist_ok=True)
        topics.WriteText(srqpath, (
            "---\ntype: rq\ntitle: 核心研究问题\naliases: [rq-main]\n"
            "sources: []\ntags: [待完善]\ncreated: %s\nupdated: %s\n---\n\n"
            "# 核心研究问题\n\n"
            "> 论文题目：%s\n"
            "> 请在「研究规则 → 研究目标」中完善 RQ1，再在此页展开论述。\n\n"
            "## 问题表述\n\n（待填写）\n\n"
            "## 文献现状\n\n（待填写）\n\n"
            "## 本研究的切入点\n\n（待填写）\n"
        ) % (stamp, stamp, stitle))

    import wiki_refresh as refresh
    refresh.RefreshWiki(bwrite_files=True, bforce=True)
    core.AppendLog("[onboarding] 完成入门设置：%s" % stitle)

    ostate = LoadOnboarding()
    ostate["welcome_done"] = True
    ostate["welcome_skipped"] = False
    ostate["setup_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    ostate["setup_title"] = stitle
    SaveOnboarding(ostate)
    return {"status": "ok", "title": stitle}


def DismissWelcome():
    ostate = LoadOnboarding()
    ostate["welcome_done"] = True
    ostate["welcome_skipped"] = True
    SaveOnboarding(ostate)
    return {"status": "ok"}


def DismissChecklist():
    ostate = LoadOnboarding()
    ostate["checklist_dismissed"] = True
    SaveOnboarding(ostate)
    return {"status": "ok"}
