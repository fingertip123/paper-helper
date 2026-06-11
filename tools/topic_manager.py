#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""多选题管理：切换、新建、重置、规则文件读写。"""
import os
import re
import json
import shutil
from datetime import datetime

# 由 wiki_core 在初始化后注入（勿与 wiki_core.rootdir 混用）
_datadir = ""
_layout_ready = False

wikisubdirs = [
    "sources", "concepts", "entities", "research-questions",
    "experiments", "synthesis", "comparisons", "queries",
]

# purpose 填空字段（key, 标签, 是否必填）—— 仅论文题目必填
purposefields = [
    ("working_title", "论文题目", True),
    ("direction", "研究方向", False),
    ("rq1", "研究问题 RQ1", False),
    ("rq2", "研究问题 RQ2", False),
    ("rq3", "研究问题 RQ3", False),
    ("rq4", "研究问题 RQ4", False),
    ("scope_include", "研究范围 · 包含", False),
    ("scope_exclude", "研究范围 · 不包含", False),
    ("thesis", "当前论点 / 假设", False),
    ("outline", "论文章节规划", False),
    ("milestones", "关键里程碑", False),
]


def Init(nroot):
    global _datadir
    _datadir = nroot
    EnsureLayout()


def ConfigDir():
    return os.path.join(_datadir, ".paper-helper")


def TopicsDir():
    return os.path.join(_datadir, "topics")


def GetTemplatesDir():
    return os.path.join(_datadir, "templates")


def CurrentTopicPath():
    return os.path.join(ConfigDir(), "current_topic.json")


def GetCurrentTopicId():
    if not _layout_ready:
        EnsureLayout()
    if not os.path.isfile(CurrentTopicPath()):
        return None
    with open(CurrentTopicPath(), "r", encoding="utf-8") as f:
        return json.load(f).get("id")


def GetTopicDir(ntopicid=None):
    nid = ntopicid or GetCurrentTopicId()
    if not nid:
        return _datadir
    return os.path.join(TopicsDir(), nid)


def RulePath(sname, ntopicid=None):
    return os.path.join(GetTopicDir(ntopicid), sname)


def GetTemplateFile(sname):
    return os.path.join(GetTemplatesDir(), sname)


def MetaPath(ntopicid):
    return os.path.join(TopicsDir(), ntopicid, "meta.json")


def ReadText(spath, sdefault=""):
    if not os.path.isfile(spath):
        return sdefault
    with open(spath, "r", encoding="utf-8") as f:
        return f.read()


def WriteText(spath, scontent):
    os.makedirs(os.path.dirname(spath), exist_ok=True)
    with open(spath, "w", encoding="utf-8") as f:
        f.write(scontent)


def SaveCurrentTopic(ntopicid):
    os.makedirs(ConfigDir(), exist_ok=True)
    with open(CurrentTopicPath(), "w", encoding="utf-8") as f:
        json.dump({"id": ntopicid}, f, ensure_ascii=False)


def ReadMeta(ntopicid):
    spath = MetaPath(ntopicid)
    if not os.path.isfile(spath):
        return {"id": ntopicid, "name": ntopicid, "created": "", "updated": ""}
    with open(spath, "r", encoding="utf-8") as f:
        return json.load(f)


def WriteMeta(ntopicid, oname):
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    opath = MetaPath(ntopicid)
    ometa = ReadMeta(ntopicid)
    ometa.update({"id": ntopicid, "name": oname, "updated": stamp})
    if not ometa.get("created"):
        ometa["created"] = stamp
    os.makedirs(os.path.dirname(opath), exist_ok=True)
    with open(opath, "w", encoding="utf-8") as f:
        json.dump(ometa, f, ensure_ascii=False, indent=2)


def EnsureTemplates():
    os.makedirs(GetTemplatesDir(), exist_ok=True)
    os.makedirs(os.path.join(GetTemplatesDir(), "wiki"), exist_ok=True)
    spurpose_tpl = GetTemplateFile("purpose.md")
    if not os.path.isfile(spurpose_tpl):
        WriteText(spurpose_tpl, RenderPurpose({"working_title": "（待填写）"}))
    for sname in ("schema.md", "AGENTS.md"):
        stpl = GetTemplateFile(sname)
        sroot = os.path.join(_datadir, sname)
        if not os.path.isfile(stpl) and os.path.isfile(sroot):
            shutil.copy2(sroot, stpl)
    swikisrc = os.path.join(_datadir, "wiki")
    swikidst = os.path.join(GetTemplatesDir(), "wiki")
    if os.path.isdir(swikisrc):
        for ssub in wikisubdirs:
            stplf = os.path.join(swikisrc, ssub, "_template.md")
            if os.path.isfile(stplf):
                os.makedirs(os.path.join(swikidst, ssub), exist_ok=True)
                sdstf = os.path.join(swikidst, ssub, "_template.md")
                if not os.path.isfile(sdstf):
                    shutil.copy2(stplf, sdstf)


def CopyWikiTemplates(ntopicdir):
    swikidst = os.path.join(ntopicdir, "wiki")
    swikisrc = os.path.join(GetTemplatesDir(), "wiki")
    for ssub in wikisubdirs:
        os.makedirs(os.path.join(swikidst, ssub), exist_ok=True)
        stpl = os.path.join(swikisrc, ssub, "_template.md")
        if os.path.isfile(stpl):
            shutil.copy2(stpl, os.path.join(swikidst, ssub, "_template.md"))
    for sname in ("index.md", "log.md", "overview.md"):
        WriteText(os.path.join(swikidst, sname), "---\ntype: meta\ntitle: %s\n---\n\n" % sname)


def InitTopicDirs(ntopicdir):
    os.makedirs(os.path.join(ntopicdir, "raw", "sources"), exist_ok=True)
    os.makedirs(os.path.join(ntopicdir, "raw", "assets"), exist_ok=True)
    CopyWikiTemplates(ntopicdir)


def MigrateLegacy():
    """首次运行：把根目录 wiki/raw/规则 迁入 topics/default。"""
    if os.path.isfile(CurrentTopicPath()):
        return
    EnsureTemplates()
    nid = "default"
    ntdir = os.path.join(TopicsDir(), nid)
    if os.path.isdir(ntdir):
        SaveCurrentTopic(nid)
        WriteMeta(nid, "默认选题")
        return nid
    os.makedirs(ntdir, exist_ok=True)
    for sitem in ("wiki", "raw"):
        ssrc = os.path.join(_datadir, sitem)
        sdst = os.path.join(ntdir, sitem)
        if os.path.isdir(ssrc) and not os.path.exists(sdst):
            shutil.copytree(ssrc, sdst)
        elif not os.path.exists(sdst):
            os.makedirs(sdst, exist_ok=True)
    for sname in ("purpose.md", "schema.md", "AGENTS.md"):
        ssrc = os.path.join(_datadir, sname)
        sdst = os.path.join(ntdir, sname)
        if os.path.isfile(ssrc) and not os.path.isfile(sdst):
            shutil.copy2(ssrc, sdst)
        elif not os.path.isfile(sdst) and os.path.isfile(GetTemplateFile(sname)):
            shutil.copy2(GetTemplateFile(sname), sdst)
    if not os.path.isdir(os.path.join(ntdir, "wiki")):
        InitTopicDirs(ntdir)
    WriteMeta(nid, "默认选题")
    SaveCurrentTopic(nid)


def EnsureLayout():
    global _layout_ready
    if _layout_ready:
        return
    os.makedirs(TopicsDir(), exist_ok=True)
    os.makedirs(ConfigDir(), exist_ok=True)
    MigrateLegacy()
    SyncAllTopicMetaNames()
    _layout_ready = True


def CleanImportedFields(ofields):
    """导入时去掉占位符，避免写入表单。"""
    oclean = {}
    for skey, sval in ofields.items():
        sval = (sval or "").strip()
        if sval in ("（未填写）", "（待填写）"):
            sval = ""
        oclean[skey] = sval
    return oclean


def GetTopicWorkingTitle(ntopicid):
    ofields = ParsePurposeFields(ReadText(RulePath("purpose.md", ntopicid)))
    stitle = (ofields.get("working_title") or "").strip()
    if stitle in ("（未填写）", "（待填写）", ""):
        return ""
    return stitle


def GetTopicDisplayName(ntopicid):
    stitle = GetTopicWorkingTitle(ntopicid)
    if stitle:
        return stitle
    return ReadMeta(ntopicid).get("name", ntopicid)


def SyncTopicMetaName(ntopicid):
    """若 purpose 中已有论文题目，同步写入 meta.name。"""
    sdisplay = GetTopicDisplayName(ntopicid)
    ometa = ReadMeta(ntopicid)
    if sdisplay and sdisplay != ometa.get("name"):
        WriteMeta(ntopicid, sdisplay)


def SyncAllTopicMetaNames():
    if not os.path.isdir(TopicsDir()):
        return
    for sname in os.listdir(TopicsDir()):
        if os.path.isdir(os.path.join(TopicsDir(), sname)):
            SyncTopicMetaName(sname)


def GetTopicConfig(ntopicid):
    """读取指定选题的完整规则配置（供一键导入）。"""
    if not os.path.isdir(GetTopicDir(ntopicid)):
        raise ValueError("选题不存在")
    ofields = CleanImportedFields(ParsePurposeFields(ReadText(RulePath("purpose.md", ntopicid))))
    sdisplay = GetTopicDisplayName(ntopicid)
    return {
        "id": ntopicid,
        "name": sdisplay,
        "working_title": GetTopicWorkingTitle(ntopicid) or sdisplay,
        "fields": ofields,
        "schema": ReadText(RulePath("schema.md", ntopicid)),
        "agents": ReadText(RulePath("AGENTS.md", ntopicid)),
    }


def ListTopics():
    if not _layout_ready:
        EnsureLayout()
    vtopics = []
    if not os.path.isdir(TopicsDir()):
        return vtopics
    for sname in sorted(os.listdir(TopicsDir())):
        spath = os.path.join(TopicsDir(), sname)
        if os.path.isdir(spath):
            ometa = ReadMeta(sname)
            sdisplay = GetTopicDisplayName(sname)
            vtopics.append({
                "id": sname,
                "name": sdisplay,
                "working_title": GetTopicWorkingTitle(sname) or sdisplay,
                "created": ometa.get("created", ""),
                "updated": ometa.get("updated", ""),
                "current": sname == GetCurrentTopicId(),
            })
    vtopics.sort(key=lambda x: x.get("updated", ""), reverse=True)
    return vtopics


def ParsePurposeFields(scontent):
    """从 purpose.md 提取填空字段（供参考/一键填入）。"""
    ofields = {k: "" for k, _, _ in purposefields}
    if not scontent:
        return ofields
    opatterns = [
        ("working_title", r"## 1\. 论文主题.*?\n\n- \*\*方向\*\*：(.+?)\n- \*\*当前标题[^：]*\*\*：(.+?)\n"),
        ("direction", r"\*\*方向\*\*：(.+?)\n"),
        ("working_title", r"\*\*当前标题[^：]*\*\*：(.+?)\n"),
        ("rq1", r"- RQ1：(.+?)\n"),
        ("rq2", r"- RQ2：(.+?)\n"),
        ("rq3", r"- RQ3：(.+?)\n"),
        ("rq4", r"- RQ4[^：]*：(.+?)\n"),
        ("scope_include", r"- \*\*包含\*\*：(.+?)\n"),
        ("scope_exclude", r"- \*\*不包含\*\*：(.+?)\n"),
        ("thesis", r"## 4\. 当前论点.*?\n\n(.+?)(?=\n## |\Z)"),
        ("outline", r"## 5\. 论文章节规划.*?\n\n(.+?)(?=\n## |\Z)"),
        ("milestones", r"## 6\. 关键里程碑.*?\n\n(.+?)(?=\n## |\Z)"),
    ]
    for skey, spattern in opatterns:
        om = re.search(spattern, scontent, re.DOTALL)
        if om:
            ofields[skey] = om.group(om.lastindex).strip()
    return ofields


def FmtPurposeVal(ofields, skey, brequired=False):
    sval = (ofields.get(skey) or "").strip()
    if sval:
        return sval
    return "（待填写）" if brequired else "（未填写）"


def ValidatePurposeFields(ofields):
    if not (ofields.get("working_title") or "").strip():
        raise ValueError("请填写论文题目")


def RenderPurpose(ofields):
    """由填空字段生成 purpose.md。"""
    ValidatePurposeFields(ofields)
    stamp = datetime.now().strftime("%Y-%m-%d")
    srq4 = ofields.get("rq4", "").strip()
    srq4line = ("- RQ4：%s\n" % srq4) if srq4 else ""
    return (
        "---\ntype: purpose\ntitle: 博士论文 Wiki 的目标\nupdated: %s\n---\n\n"
        "# Purpose · 这个 Wiki 为什么存在\n\n"
        "> 这是整个知识库的「灵魂」。Agent 在每次摄入 / 查询前都会先读它。\n\n"
        "## 1. 论文主题 / Working Title\n\n"
        "- **方向**：%s\n"
        "- **当前标题（暂定）**：%s\n\n"
        "## 2. 核心研究问题（Research Questions）\n\n"
        "- RQ1：%s\n"
        "- RQ2：%s\n"
        "- RQ3：%s\n"
        "%s\n"
        "## 3. 研究范围（Scope）\n\n"
        "- **包含**：%s\n"
        "- **不包含**：%s\n\n"
        "## 4. 当前论点 / 假设（Evolving Thesis）\n\n"
        "%s\n\n"
        "## 5. 论文章节规划（Outline）\n\n"
        "%s\n\n"
        "## 6. 关键里程碑（Milestones）\n\n"
        "%s\n"
    ) % (
        stamp,
        FmtPurposeVal(ofields, "direction"),
        FmtPurposeVal(ofields, "working_title", True),
        FmtPurposeVal(ofields, "rq1"),
        FmtPurposeVal(ofields, "rq2"),
        FmtPurposeVal(ofields, "rq3"),
        srq4line,
        FmtPurposeVal(ofields, "scope_include"),
        FmtPurposeVal(ofields, "scope_exclude"),
        FmtPurposeVal(ofields, "thesis"),
        FmtPurposeVal(ofields, "outline"),
        FmtPurposeVal(ofields, "milestones"),
    )


def GetRules(sonly=None):
    """读取当前选题规则文件；purpose 同时返回填空字段。"""
    oresult = {}
    vnames = [sonly] if sonly else ("purpose", "schema", "agents")
    smap = {"purpose": "purpose.md", "schema": "schema.md", "agents": "AGENTS.md"}
    for skey in vnames:
        sfile = smap.get(skey)
        if not sfile:
            continue
        scontent = ReadText(RulePath(sfile))
        stpl = ReadText(GetTemplateFile(sfile))
        oitem = {"content": scontent, "template": stpl}
        if skey == "purpose":
            oitem["fields"] = ParsePurposeFields(scontent)
            oitem["field_labels"] = GetPurposeFieldDefs()
        oresult[skey] = oitem
    return oresult


def SaveRule(skey, scontent=None, ofields=None):
    smap = {"purpose": "purpose.md", "schema": "schema.md", "agents": "AGENTS.md"}
    sfile = smap.get(skey)
    if not sfile:
        raise ValueError("未知规则类型")
    if skey == "purpose" and ofields:
        ValidatePurposeFields(ofields)
        scontent = RenderPurpose(ofields)
    if scontent is None:
        raise ValueError("缺少内容")
    WriteText(RulePath(sfile), scontent)
    nid = GetCurrentTopicId()
    if nid:
        if skey == "purpose" and ofields:
            sdisplay = (ofields.get("working_title") or "").strip() or ReadMeta(nid).get("name", nid)
            WriteMeta(nid, sdisplay)
        else:
            SyncTopicMetaName(nid)


def ClearWikiContent(ntopicdir):
    """删除 wiki 中除 _template.md 外的所有页面。"""
    swikidir = os.path.join(ntopicdir, "wiki")
    if not os.path.isdir(swikidir):
        return
    for sroot, _, vfiles in os.walk(swikidir):
        for sname in vfiles:
            if sname == "_template.md":
                continue
            os.remove(os.path.join(sroot, sname))


def ClearRawSources(ntopicdir):
    srawdir = os.path.join(ntopicdir, "raw", "sources")
    if os.path.isdir(srawdir):
        shutil.rmtree(srawdir)
    os.makedirs(srawdir, exist_ok=True)


def ResetCurrentTopic():
    """一键重置：清空文献与分析页，purpose 恢复范本，保留 schema/AGENTS。"""
    nid = GetCurrentTopicId()
    if not nid:
        raise ValueError("无当前选题")
    ntdir = GetTopicDir(nid)
    ClearWikiContent(ntdir)
    ClearRawSources(ntdir)
    CopyWikiTemplates(ntdir)
    if os.path.isfile(GetTemplateFile("purpose.md")):
        shutil.copy2(GetTemplateFile("purpose.md"), RulePath("purpose.md", nid))
    else:
        WriteText(RulePath("purpose.md", nid), RenderPurpose({}))
    WriteMeta(nid, ReadMeta(nid).get("name", nid))
    return {"id": nid, "name": GetTopicDisplayName(nid)}


def CreateTopic(sname, ofields=None, bcopyrules=True, nimportfrom=None):
    """新建选题：旧选题保留；schema/AGENTS 默认从当前复制，可通过 nimportfrom 从指定选题导入。"""
    EnsureLayout()
    nid = "topic-" + datetime.now().strftime("%Y%m%d-%H%M%S")
    ntdir = os.path.join(TopicsDir(), nid)
    if os.path.exists(ntdir):
        raise ValueError("选题已存在")
    os.makedirs(ntdir, exist_ok=True)
    InitTopicDirs(ntdir)
    sold = nimportfrom if nimportfrom else GetCurrentTopicId()
    if bcopyrules and sold:
        for sname in ("schema.md", "AGENTS.md"):
            ssrc = RulePath(sname, sold)
            if os.path.isfile(ssrc):
                shutil.copy2(ssrc, os.path.join(ntdir, sname))
    else:
        for sname in ("schema.md", "AGENTS.md"):
            if os.path.isfile(GetTemplateFile(sname)):
                shutil.copy2(GetTemplateFile(sname), os.path.join(ntdir, sname))
    if ofields:
        ValidatePurposeFields(ofields)
        WriteText(os.path.join(ntdir, "purpose.md"), RenderPurpose(ofields))
    elif os.path.isfile(GetTemplateFile("purpose.md")):
        shutil.copy2(GetTemplateFile("purpose.md"), os.path.join(ntdir, "purpose.md"))
    else:
        WriteText(os.path.join(ntdir, "purpose.md"), RenderPurpose({}))
    sdisplay = (sname or "").strip()
    if not sdisplay and ofields:
        sdisplay = (ofields.get("working_title") or "").strip()
    if not sdisplay:
        sdisplay = "新选题"
    WriteMeta(nid, sdisplay)
    SaveCurrentTopic(nid)
    return {"id": nid, "name": sdisplay}


def SwitchTopic(ntopicid):
    spath = os.path.join(TopicsDir(), ntopicid)
    if not os.path.isdir(spath):
        raise ValueError("选题不存在")
    SaveCurrentTopic(ntopicid)
    return {"id": ntopicid, "name": GetTopicDisplayName(ntopicid)}


def GetPurposeFieldDefs():
    return [{"key": k, "label": lb, "required": req} for k, lb, req in purposefields]
