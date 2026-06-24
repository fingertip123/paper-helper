#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""五阶段深度文献分析引擎（与「纳入研究」分工不同）。

纳入 = 入库 + 组网（精简摘要）；深度 = 单篇方法论审计 + 跨文献对撞 + 写作素材。
阶段① 结构解剖 → ② 方法论红队 → ③ RQ/论点对齐 → ④ 跨文献对撞 → ⑤ 报告整合
输出：wiki/analysis/<key>-report.md，并在 source 页追加「深度研究摘要」。
"""
import os
import re
import json
import threading

import wiki_core as core
import topic_manager as topics
from app import CallLlm, ExtractPaperText, ParseLlmJson, IsIngestCancelled, SafeName

deepjob = {}
deeplock = threading.Lock()

PDF_MISSING_MSG = "找不到原始 PDF 文件。深度研究需要 PDF 原文，请重新上传后再试。"
NOT_INGESTED_MSG = "该文献尚未「纳入研究」，请先纳入后再进行深度分析。"


def _Now():
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d")


def _LoadExistingWikiContext():
    """收集已有 wiki 页面作为跨文献分析上下文。"""
    vnodes, _ = core.ScanWiki()
    vsources = [n for n in vnodes if n.get("type") == "source" and n.get("ingested")]
    vconcepts = [n for n in vnodes if n.get("type") == "concept"]
    vrqs = [n for n in vnodes if n.get("type") == "rq"]
    sprior = "\n".join("- [[%s]]: %s" % (n["id"], n.get("summary", "")[:100])
                       for n in vsources[:20])
    sconcepts = "\n".join("- [[%s]]: %s" % (n["id"], n.get("summary", "")[:80])
                          for n in vconcepts[:15])
    srqs = "\n".join("- [[%s]]: %s" % (n["id"], n.get("title", ""))
                     for n in vrqs[:10])
    return sprior, sconcepts, srqs, vnodes


def _ReadPurpose():
    sp = topics.ReadText(topics.RulePath("purpose.md"))
    return (sp or "")[:4000]


def _ReadPurposeRqs():
    sp = topics.ReadText(topics.RulePath("purpose.md"))
    ofields = topics.ParsePurposeFields(sp or "")
    vrqlines = []
    for skey in ("rq1", "rq2", "rq3", "rq4"):
        sval = (ofields.get(skey) or "").strip()
        if sval and sval not in ("（待填写）", "（未填写）"):
            vrqlines.append(sval)
    sthesis = (ofields.get("thesis") or "").strip()[:1200]
    return "\n".join(vrqlines) if vrqlines else "（尚未填写具体研究问题）", sthesis


def _ReadSourcePage(skey):
    spath = os.path.join(core.wikidir, "sources", skey + ".md")
    if os.path.isfile(spath):
        with open(spath, "r", encoding="utf-8") as f:
            return f.read()
    return ""


def _ResolvePdfPath(nfilename, skey=None):
    """解析 PDF 路径；缺失时抛出带指引的异常。"""
    sfile = SafeName(nfilename or "")
    if not sfile and skey:
        sfile = SafeName(core.ResolveRawfileForKey(skey))
    if not sfile:
        raise FileNotFoundError(PDF_MISSING_MSG)
    fullpath = os.path.join(core.rawsourcesdir, sfile)
    if not os.path.isfile(fullpath):
        raise FileNotFoundError(PDF_MISSING_MSG)
    return fullpath, sfile


def _LlmJson(oconfig, system, user, nmaxuser=8000):
    content = CallLlm(oconfig, [
        {"role": "system", "content": system},
        {"role": "user", "content": user[:nmaxuser] if len(user) > nmaxuser else user},
    ], bjson=True, fcancel=IsIngestCancelled)
    return ParseLlmJson(content) if isinstance(content, str) else content


def _LlmText(oconfig, system, user, nmaxuser=12000):
    return CallLlm(oconfig, [
        {"role": "system", "content": system},
        {"role": "user", "content": user[:nmaxuser] if len(user) > nmaxuser else user},
    ], bjson=False, fcancel=IsIngestCancelled)


# ---- 阶段① 结构解剖 ----
def _Stage1Structure(oconfig, npapertext, skey, stitle, ssourcepage):
    system = (
        "你是论文结构解剖专家。从 PDF 全文中提取方法论相关结构，输出 JSON。"
        "纳入研究阶段已有精简摘要（见 user），请勿重复摘要，专注假设链、识别策略、变量与结果。"
    )
    user = (
        "## 论文\n标题：%s\n引用 key：%s\n\n"
        "## 已纳入 wiki 摘要（勿重复）\n%s\n\n"
        "## PDF 全文\n%s\n\n"
        "输出 JSON 字段：research_topic, theoretical_tradition, core_argument, "
        "hypothesis_chain[], implicit_assumptions[], identification_strategy, "
        "data_description, key_variables[{name,type,measurement}], "
        "main_results[{estimate,se,significance}], robustness_checks[], "
        "internal_validity[], external_validity, key_references[], limitations[]。"
        "找不到的字段留空，不要臆造。"
        % (stitle, skey, (ssourcepage or "（无）")[:3000], npapertext[:24000])
    )
    return _LlmJson(oconfig, system, user, 28000)


# ---- 阶段② 方法论红队 ----
def _Stage2RedTeam(oconfig, skey, stitle, ostruct):
    system = (
        "你是方法论「红队」审查员。任务：逐条挑战识别策略与测量，找替代解释与推理漏洞。"
        "不做 RQ 对齐（下一阶段专门做）。输出 JSON。"
    )
    user = (
        "## 论文：%s（%s）\n\n## 结构解剖\n%s\n\n"
        "输出 JSON：methodology_rating, design_strengths[], design_weaknesses[], "
        "identification_issues, measurement_validity, alternative_explanations[], "
        "result_reliability, red_team_verdict（一段话总结最大风险）。"
        % (stitle, skey, json.dumps(ostruct, ensure_ascii=False, indent=2)[:9000])
    )
    return _LlmJson(oconfig, system, user)


# ---- 阶段③ RQ/论点对齐 ----
def _Stage3RqThesis(oconfig, skey, stitle, ostruct, ored, spurpose, srqctx, sthesis):
    system = (
        "你是研究问题对齐专家。基于 purpose 中每条 RQ 与用户论点，"
        "论证级评估本篇文献的关联强度（不是标签式链接）。输出 JSON。"
    )
    user = (
        "## 论文：%s（%s）\n\n## 结构\n%s\n\n## 红队结论\n%s\n\n"
        "## purpose 研究问题\n%s\n\n## 当前论点\n%s\n\n"
        "输出 JSON：rq_alignment[{rq,alignment,reason,evidence}], "
        "thesis_implication, supports_thesis[], challenges_thesis[], "
        "gap_for_user_research（对用户论文尚缺的启示）。"
        % (stitle, skey,
           json.dumps(ostruct, ensure_ascii=False)[:4000],
           json.dumps(ored, ensure_ascii=False)[:4000],
           srqctx, sthesis or "（未填写）")
    )
    return _LlmJson(oconfig, system, user)


# ---- 阶段④ 跨文献对撞 ----
def _Stage4CrossLit(oconfig, skey, stitle, ostruct, sprior_sources, sconcepts):
    system = (
        "你是跨文献对比专家。将本篇与知识库中已纳入文献做系统性方法/结论对撞。"
        "必须引用具体 [[wikilink]]。输出 JSON。"
    )
    user = (
        "## 目标文献：%s（%s）\n\n## 本篇结构要点\n%s\n\n"
        "## 库内已纳入文献\n%s\n\n## 已有概念\n%s\n\n"
        "输出 JSON：consensus_with[{source,point}], tensions_with[{source,point}], "
        "method_contrasts[{source,this_method,other_method}], "
        "complementary_sources[{source,how}], synthesis_position（本篇在文献谱系中的位置）。"
        % (stitle, skey, json.dumps(ostruct, ensure_ascii=False)[:5000],
           sprior_sources or "（无）", sconcepts or "（无）")
    )
    return _LlmJson(oconfig, system, user)


# ---- 阶段⑤ 写作素材 + 报告正文 ----
def _Stage5Report(oconfig, skey, stitle, ostruct, ored, orq, ocross, spurpose, srqs):
    system = (
        "你是博士论文写作助手。基于前五阶段 JSON 结果，生成完整深度研究报告 Markdown 正文"
        "（不含 YAML frontmatter）。必须含 ## 1–9 章节，并额外含 ## 10. 写作素材。"
        "使用 [[wikilink]]。不臆造文献中没有的内容。"
    )
    user = (
        "## 论文：%s（%s）\n\n## 结构解剖\n%s\n\n## 方法论红队\n%s\n\n"
        "## RQ/论点对齐\n%s\n\n## 跨文献对撞\n%s\n\n## 研究目标\n%s\n\n## 已有 RQ 页\n%s\n\n"
        "章节要求：\n"
        "## 1. 论文定位与全景\n## 2. 理论基础与假设推演\n"
        "## 3. 方法论深度评估（含 3.1–3.5 子节）\n## 4. 核心实证结果解读\n"
        "## 5. 与当前研究问题的关系\n## 6. 跨文献对比\n## 7. 可借鉴的研究设计\n"
        "## 8. 关键引用网络\n## 9. 疑点与待核实项\n"
        "## 10. 写作素材\n"
        "- 10.1 可直接写入综述的段落（2–3 段）\n"
        "- 10.2 可复制的研究设计清单\n"
        % (stitle, skey,
           json.dumps(ostruct, ensure_ascii=False)[:3500],
           json.dumps(ored, ensure_ascii=False)[:3500],
           json.dumps(orq, ensure_ascii=False)[:3500],
           json.dumps(ocross, ensure_ascii=False)[:3500],
           spurpose[:2500], srqs or "（无）")
    )
    return _LlmText(oconfig, system, user, 14000)


def _BriefFromStages(skey, ostruct, ored, orq):
    """生成 3–5 句深度研究摘要，写入 source 页。"""
    sparts = []
    if ostruct.get("core_argument"):
        sparts.append(str(ostruct["core_argument"])[:200])
    if ored.get("methodology_rating"):
        sparts.append("方法论评级：" + str(ored["methodology_rating"])[:120])
    if orq.get("thesis_implication"):
        sparts.append(str(orq["thesis_implication"])[:200])
    if ored.get("red_team_verdict"):
        sparts.append(str(ored["red_team_verdict"])[:180])
    if sparts:
        return "\n\n".join(sparts[:4]) + "\n\n完整报告：[[%s-report]]" % skey
    return "完整报告：[[%s-report]]" % skey


def _AppendDeepSummaryToSource(skey, ssummary):
    """在 source 页追加或更新「深度研究摘要」节。"""
    spath = os.path.join(core.wikidir, "sources", skey + ".md")
    if not os.path.isfile(spath) or not ssummary.strip():
        return
    with open(spath, "r", encoding="utf-8") as f:
        ntext = f.read()
    ssection = "## 深度研究摘要\n\n" + ssummary.strip() + "\n"
    if "## 深度研究摘要" in ntext:
        ntext = re.sub(
            r"\n## 深度研究摘要\n[\s\S]*?(?=\n## |\Z)",
            "\n" + ssection,
            ntext,
            count=1,
        )
    else:
        ntext = ntext.rstrip() + "\n\n" + ssection
    with open(spath, "w", encoding="utf-8") as f:
        f.write(ntext)


def DeepAnalyzePaper(oconfig, nfilename, skey=None):
    """五阶段深度分析主流程。"""
    fullpath, sfile = _ResolvePdfPath(nfilename, skey)
    meta = core.ParseSourceFilename(sfile)
    skey = skey or meta["key"]
    stitle = meta.get("title") or skey

    ssourcepage = _ReadSourcePage(skey)
    if not ssourcepage:
        raise ValueError(NOT_INGESTED_MSG)

    update_callback(5, "准备")
    text = ExtractPaperText(fullpath)
    if not text.strip():
        raise ValueError("无法从 PDF 提取文本（可能是扫描版），请换用可搜索的 PDF 后重试")

    spurpose = _ReadPurpose()
    srqctx, sthesis = _ReadPurposeRqs()
    sprior_sources, sconcepts, srqs, _ = _LoadExistingWikiContext()

    update_callback(15, "阶段① 结构解剖")
    core.AppendLog("[deep] %s：阶段① 结构解剖" % skey)
    ostruct = _Stage1Structure(oconfig, text, skey, stitle, ssourcepage)

    update_callback(35, "阶段② 方法论红队")
    core.AppendLog("[deep] %s：阶段② 方法论红队" % skey)
    ored = _Stage2RedTeam(oconfig, skey, stitle, ostruct)

    update_callback(55, "阶段③ RQ/论点对齐")
    core.AppendLog("[deep] %s：阶段③ RQ/论点对齐" % skey)
    orq = _Stage3RqThesis(oconfig, skey, stitle, ostruct, ored, spurpose, srqctx, sthesis)

    update_callback(72, "阶段④ 跨文献对撞")
    core.AppendLog("[deep] %s：阶段④ 跨文献对撞" % skey)
    ocross = _Stage4CrossLit(oconfig, skey, stitle, ostruct, sprior_sources, sconcepts)

    update_callback(88, "阶段⑤ 报告整合")
    core.AppendLog("[deep] %s：阶段⑤ 报告整合" % skey)
    report_md = _Stage5Report(oconfig, skey, stitle, ostruct, ored, orq, ocross, spurpose, srqs)

    update_callback(96, "写入报告")
    frontmatter = (
        "---\n"
        "type: analysis-report\n"
        "title: 深度研究报告 — %s\n"
        "sources: [%s]\n"
        "created: %s\n"
        "updated: %s\n"
        "---\n\n"
    ) % (stitle, skey, _Now(), _Now())
    full_report = (
        frontmatter
        + "# 深度研究报告：%s\n\n> 五阶段分析生成。原始文献：[[%s]]\n\n"
        % (stitle, skey)
        + report_md
    )

    analysis_dir = os.path.join(core.wikidir, "analysis")
    os.makedirs(analysis_dir, exist_ok=True)
    report_path = os.path.join(analysis_dir, "%s-report.md" % skey)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(full_report)

    sbrief = _BriefFromStages(skey, ostruct, ored, orq)
    _AppendDeepSummaryToSource(skey, sbrief)

    core.AppendLog("[deep] %s：深度研究报告已生成（%s）" % (
        skey, os.path.relpath(report_path, core.rootdir)))
    core.GenerateIndex()
    update_callback(100, "完成")

    return {
        "key": skey,
        "file": sfile,
        "report": os.path.relpath(report_path, core.rootdir),
        "title": stitle,
    }


# ---- 进度回调与线程 ----
def _DefaultUpdateCb(npct, sstage=""):
    with deeplock:
        deepjob["progress"] = npct
        if sstage:
            deepjob["stage"] = sstage


update_callback = _DefaultUpdateCb


def GetDeepJobStatus():
    with deeplock:
        return dict(deepjob)


def _RunDeepJob(oconfig, nfilename, sroot=None, skey=None):
    import app as appmod  # noqa: E402 — 绑定多用户数据根与 config 路径
    global update_callback
    update_callback = _DefaultUpdateCb
    appmod.datalock.acquire()
    try:
        if sroot and appmod.multiuser:
            appmod.BindDataRoot(sroot)
        with deeplock:
            deepjob["running"] = True
            deepjob["finished"] = False
            deepjob["progress"] = 0
            deepjob["stage"] = "准备"
            deepjob["current"] = nfilename or skey or ""
            deepjob["error"] = ""
            deepjob["result"] = None

        oresult = DeepAnalyzePaper(oconfig, nfilename or "", skey=skey)

        with deeplock:
            deepjob["result"] = oresult
            deepjob["finished"] = True
            deepjob["progress"] = 100
            deepjob["error"] = ""
    except Exception as e:
        with deeplock:
            deepjob["error"] = str(e)
            deepjob["finished"] = True
            deepjob["progress"] = -1
    finally:
        appmod.datalock.release()
        with deeplock:
            deepjob["running"] = False


def StartDeepAnalysis(oconfig, nfilename, sroot=None, skey=None):
    global deepjob
    with deeplock:
        if deepjob.get("running"):
            return {"error": "深度分析正在进行中，请等待完成"}
        deepjob = {
            "running": True,
            "finished": False,
            "progress": 0,
            "current": nfilename or skey or "",
            "error": "",
            "result": None,
            "stage": "准备",
        }
    t = threading.Thread(
        target=_RunDeepJob,
        args=(oconfig, nfilename, sroot),
        kwargs={"skey": skey},
        daemon=True,
    )
    t.start()
    return {"status": "started", "file": nfilename or skey or ""}
