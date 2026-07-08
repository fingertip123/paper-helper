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
import time
import logging
import threading

import wiki_core as core
import topic_manager as topics
from io_utils import SafeName
from paper_io import ExtractPaperText
from paper_sections import PackForDeep
from llm_client import CallLlm, ParseLlmJson, IngestCancelled
from job_state import (
    ResetJobDict, ReleaseLlm, TryAcquireLlm, LlmBusyPayload,
    BeginDeepJob, GetDeepJob, GetDeepJobStatus, GetDeepActiveUid,
    DeepJobAlive, IsDeepCancelled, UpdateDeepProgress, deeplock,
)

logger = logging.getLogger(__name__)

DEEP_TIMEOUT_SEC = 1800

PDF_MISSING_MSG = "找不到原始 PDF 文件。深度研究需要 PDF 原文，请重新上传后再试。"
NOT_INGESTED_MSG = "该文献尚未「纳入研究」，请先纳入后再进行深度分析。"


def _Now():
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d")


def _LoadExistingWikiContext():
    """收集已有 wiki 页面作为跨文献分析上下文。"""
    import wiki_refresh as refresh
    vnodes = refresh.GetWikiData()["nodes"]
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
    ], bjson=True, fcancel=IsDeepCancelled)
    return ParseLlmJson(content) if isinstance(content, str) else content


def _LlmText(oconfig, system, user, nmaxuser=12000):
    return CallLlm(oconfig, [
        {"role": "system", "content": system},
        {"role": "user", "content": user[:nmaxuser] if len(user) > nmaxuser else user},
    ], bjson=False, fcancel=IsDeepCancelled)


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
        % (stitle, skey, (ssourcepage or "（无）")[:3000], PackForDeep(npapertext))
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
vpreamblepatterns = (
    r"以下(是|为)",
    r"报告如下",
    r"正文如下",
    r"我将(根据|基于)",
    r"作为.*助手",
    r"基于(前|上述|提供|五阶段|JSON)",
    r"不含.*frontmatter",
    r"^\*\*说明",
    r"深度分析报告",
    r"生成如下",
)


def _IsReportPreamble(stext):
    if not stext:
        return False
    if re.search(r"^>\s", stext, re.M):
        return True
    for spat in vpreamblepatterns:
        if re.search(spat, stext, re.I | re.M):
            return True
    return len(stext) < 280 and not re.search(r"^##\s*1[\.\s]", stext, re.M)


def _RenumberOrderedListBlock(sblock):
    """将连续以 1. 开头的列表项改为 1. 2. 3. …"""
    vlines = sblock.split("\n")
    vout = []
    nnum = 0
    for sline in vlines:
        omatch = re.match(r"^(\s*)1\.\s+(.+)$", sline)
        if omatch:
            nnum += 1
            vout.append("%s%d. %s" % (omatch.group(1), nnum, omatch.group(2)))
        else:
            if sline.strip() == "" or re.match(r"^\s{2,}\S", sline):
                vout.append(sline)
            else:
                nnum = 0
                vout.append(sline)
    return "\n".join(vout)


def _FixSection102Numbering(smd):
    """修正 ## 10.2 小节内 ### 1. 小标题与 1. 列表编号。"""
    omatch = re.search(r"^###\s*10\.2[^\n]*\n", smd, re.M)
    if not omatch:
        return smd
    sprefix = smd[:omatch.start()]
    srest = smd[omatch.end():]
    oend = re.search(r"^##\s", srest, re.M)
    sbody = srest[:oend.start()] if oend else srest
    ssuffix = srest[oend.start():] if oend else ""
    nidx = 0

    def replHeading(m):
        nonlocal nidx
        nidx += 1
        return "### 10.2.%d %s" % (nidx, m.group(1).strip())

    sbody = re.sub(r"^###\s*1\.\s*(.+)$", replHeading, sbody, flags=re.M)
    sbody = _RenumberOrderedListBlock(sbody)
    return sprefix + smd[omatch.start():omatch.end()] + sbody + ssuffix


def NormalizeReportBody(smd, stitle=None):
    """清理深度报告正文：去元提示、修正 10.2 编号。"""
    smd = (smd or "").strip()
    if not smd:
        return smd
    smd = re.sub(r"^#\s*深度研究报告[：:][^\n]*\n+", "", smd, count=1, flags=re.M)
    smd = re.sub(r"^>\s*[^\n]*(?:Agent|阶段|分析生成|原始文献|五阶段|三阶段)[^\n]*\n+", "", smd, flags=re.M | re.I)
    smd = re.sub(r"^>\s*[^\n]+\n+", "", smd, count=3, flags=re.M)
    ostart = re.search(r"^##\s*1[\.\s]", smd, re.M)
    if ostart and ostart.start() > 0:
        spre = smd[:ostart.start()].strip()
        if _IsReportPreamble(spre):
            smd = smd[ostart.start():]
    smd = _FixSection102Numbering(smd)
    return smd.strip()


def _Stage5Report(oconfig, skey, stitle, ostruct, ored, orq, ocross, spurpose, srqs):
    system = (
        "你是博士论文写作助手。基于前五阶段 JSON 结果，生成完整深度研究报告 Markdown 正文"
        "（不含 YAML frontmatter）。必须含 ## 1–9 章节，并额外含 ## 10. 写作素材。"
        "使用 [[wikilink]]。不臆造文献中没有的内容。"
        "正文必须直接从 ## 1. 开始，禁止任何前言、说明、元提示或任务复述。"
        "10.2 小节内三级标题必须用 ### 10.2.1、### 10.2.2 递增；"
        "列表项用 1. 2. 3. 递增，禁止重复 1. 开头。"
    )
    user = (
        "## 论文：%s（%s）\n\n## 结构解剖\n%s\n\n## 方法论红队\n%s\n\n"
        "## RQ/论点对齐\n%s\n\n## 跨文献对撞\n%s\n\n## 研究目标\n%s\n\n## 已有 RQ 页\n%s\n\n"
        "章节要求（直接从 ## 1. 开始输出，不要任何开场白）：\n"
        "## 1. 论文定位与全景\n## 2. 理论基础与假设推演\n"
        "## 3. 方法论深度评估（含 3.1–3.5 子节）\n## 4. 核心实证结果解读\n"
        "## 5. 与当前研究问题的关系\n## 6. 跨文献对比\n## 7. 可借鉴的研究设计\n"
        "## 8. 关键引用网络\n## 9. 疑点与待核实项\n"
        "## 10. 写作素材\n"
        "### 10.1 可直接写入综述的段落\n"
        "### 10.2 可复制的研究设计清单（小标题用 ### 10.2.1、10.2.2…，条目用 1. 2. 3.）\n"
        % (stitle, skey,
           json.dumps(ostruct, ensure_ascii=False)[:3500],
           json.dumps(ored, ensure_ascii=False)[:3500],
           json.dumps(orq, ensure_ascii=False)[:3500],
           json.dumps(ocross, ensure_ascii=False)[:3500],
           spurpose[:2500], srqs or "（无）")
    )
    return NormalizeReportBody(_LlmText(oconfig, system, user, 14000), stitle)


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


def _WriteComparisonPage(rkey, stitle, ocross):
    """阶段④ 产出：写入 comparison 页与显式 typed 关系行。"""
    import analysis_version as aver
    comp_id = "%s-cross" % rkey
    comp_dir = os.path.join(core.wikidir, "comparisons")
    os.makedirs(comp_dir, exist_ok=True)
    spath = os.path.join(comp_dir, comp_id + ".md")
    stamp = _Now()
    vlines = ["---"]
    vlines.extend(aver.FrontmatterPipelineLines(
        "deep", aver.GetCurrentVersion("deep"),
        type="comparison",
        title="跨文献对撞 — %s" % stitle,
        sources=[rkey],
        tags=["深度研究", "跨文献"],
        created=stamp,
        updated=stamp,
    ))
    vlines.append("---")
    vlines += [
        "",
        "# 跨文献对撞：%s" % stitle,
        "",
        "> 由深度分析阶段④自动生成。原始文献：[[%s]]" % rkey,
        "",
        "## 谱系定位",
        "",
        (ocross.get("synthesis_position") or "（待补充）").strip(),
        "",
        "## 显式关系",
        "",
    ]
    for item in (ocross.get("tensions_with") or [])[:6]:
        sother = (item.get("source") or "").strip()
        if not sother:
            continue
        spoint = (item.get("point") or "").strip()[:120]
        vlines.append("- tension | [[%s]] | [[%s]] | %s" % (rkey, sother, spoint))
    for item in (ocross.get("consensus_with") or [])[:6]:
        sother = (item.get("source") or "").strip()
        if not sother:
            continue
        spoint = (item.get("point") or "").strip()[:120]
        vlines.append("- consensus | [[%s]] | [[%s]] | %s" % (rkey, sother, spoint))
    for item in (ocross.get("method_contrasts") or [])[:6]:
        sother = (item.get("source") or "").strip()
        if not sother:
            continue
        vlines.append("- comparable | [[%s]] | [[%s]]" % (rkey, sother))
    for item in (ocross.get("complementary_sources") or [])[:4]:
        sother = (item.get("source") or "").strip()
        if not sother:
            continue
        show = (item.get("how") or "").strip()[:120]
        vlines.append("- complements | [[%s]] | [[%s]] | %s" % (rkey, sother, show))
    if vlines[-1] == "":
        vlines.append("- （暂无结构化对撞，见深度报告）")
    vlines += ["", "## 方法对照", ""]
    for item in (ocross.get("method_contrasts") or [])[:8]:
        sother = item.get("source") or "?"
        vlines.append(
            "- **[[%s]]**：本篇 `%s` vs 他篇 `%s`"
            % (sother, (item.get("this_method") or "")[:60], (item.get("other_method") or "")[:60])
        )
    with open(spath, "w", encoding="utf-8") as f:
        f.write("\n".join(vlines) + "\n")
    return os.path.relpath(spath, core.rootdir)


def DeepAnalyzePaper(oconfig, nfilename, sroot=None, skey=None):
    """五阶段深度分析主流程。

    锁策略（与「纳入研究」一致）：仅在读文件 / 写文件的短临界区内持 datalock，
    耗时数分钟的 LLM 调用在锁外进行，绝不阻塞 /api/deep/progress 与 /api/data。
    """
    import app as appmod  # noqa: E402

    # ---- 阶段 0：读取上下文（持锁，绑定该用户数据根） ----
    update_callback(5, "准备")
    with appmod.UserScope(sroot):
        fullpath, sfile = _ResolvePdfPath(nfilename, skey)
        meta = core.ParseSourceFilename(sfile)
        rkey = skey or meta["key"]
        stitle = meta.get("title") or rkey
        ssourcepage = _ReadSourcePage(rkey)
        if not ssourcepage:
            raise ValueError(NOT_INGESTED_MSG)
        text = ExtractPaperText(fullpath)
        spurpose = _ReadPurpose()
        srqctx, sthesis = _ReadPurposeRqs()
        sprior_sources, sconcepts, srqs, _ = _LoadExistingWikiContext()
    if not text.strip():
        raise ValueError(
            "无法从 PDF 提取文本（可能是扫描版）。"
            "可安装 pymupdf+pytesseract 后重试，或换可搜索 PDF。"
        )

    # ---- 阶段①–⑤：纯 LLM 调用（锁外，可被进度轮询/刷新并发访问） ----
    update_callback(15, "阶段① 结构解剖")
    ostruct = _Stage1Structure(oconfig, text, rkey, stitle, ssourcepage)

    update_callback(35, "阶段② 方法论红队")
    ored = _Stage2RedTeam(oconfig, rkey, stitle, ostruct)

    update_callback(55, "阶段③ RQ/论点对齐")
    orq = _Stage3RqThesis(oconfig, rkey, stitle, ostruct, ored, spurpose, srqctx, sthesis)

    update_callback(72, "阶段④ 跨文献对撞")
    ocross = _Stage4CrossLit(oconfig, rkey, stitle, ostruct, sprior_sources, sconcepts)

    update_callback(88, "阶段⑤ 报告整合")
    report_md = _Stage5Report(oconfig, rkey, stitle, ostruct, ored, orq, ocross, spurpose, srqs)

    # ---- 阶段 6：写入报告与摘要（持锁） ----
    update_callback(96, "写入报告")
    import analysis_version as aver
    stamp = _Now()
    vfm = aver.ReportFrontmatterFields(
        "deep", aver.GetCurrentVersion("deep"),
        "深度研究报告 — %s" % stitle, rkey, stamp,
    )
    frontmatter = "---\n" + "\n".join(vfm) + "\n---\n\n"
    full_report = (
        frontmatter
        + "# 深度研究报告：%s\n\n"
        % stitle
        + report_md
    )
    sbrief = _BriefFromStages(rkey, ostruct, ored, orq)
    with appmod.UserScope(sroot):
        analysis_dir = os.path.join(core.wikidir, "analysis")
        os.makedirs(analysis_dir, exist_ok=True)
        report_path = os.path.join(analysis_dir, "%s-report.md" % rkey)
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(full_report)
        _AppendDeepSummaryToSource(rkey, sbrief)
        scomp = _WriteComparisonPage(rkey, stitle, ocross)
        srel = os.path.relpath(report_path, core.rootdir)
        core.AppendLog("[deep] %s：深度研究报告已生成（%s）；对撞页 %s" % (rkey, srel, scomp))
        import wiki_refresh as refresh
        import wiki_workflow as wflow
        wflow.Init(core.wikidir)
        vrqids = [
            (x.get("rq") or "").strip()
            for x in (orq.get("rq_alignment") or [])
            if (x.get("rq") or "").strip()
        ]
        wflow.SyncRqPages(rkey, {"rq_links": vrqids}, (orq.get("thesis_implication") or "")[:120])
        refresh.RefreshWiki(bwrite_files=True, bforce=True)

    update_callback(100, "完成")
    return {
        "key": rkey,
        "file": sfile,
        "report": srel,
        "title": stitle,
    }


# ---- 进度回调与线程 ----
update_callback = UpdateDeepProgress


def _RunDeepJob(oconfig, nfilename, sroot=None, skey=None, nuid=0, ngen=0):
    """后台线程：执行深度分析。LLM 互斥锁已在 StartDeepAnalysis 内获取，此处仅负责释放。"""
    global update_callback
    update_callback = UpdateDeepProgress
    try:
        oresult = DeepAnalyzePaper(oconfig, nfilename or "", sroot=sroot, skey=skey)
        with deeplock:
            if DeepJobAlive(nuid, ngen):
                ojob = GetDeepJob(nuid)
                ojob["result"] = oresult
                ojob["finished"] = True
                ojob["progress"] = 100
                ojob["error"] = ""
    except IngestCancelled as e:
        with deeplock:
            if DeepJobAlive(nuid, ngen):
                ojob = GetDeepJob(nuid)
                nstart = ojob.get("started_at") or 0
                btimeout = nstart > 0 and (time.time() - nstart) > DEEP_TIMEOUT_SEC
                ojob["error"] = (
                    "深度分析已超时（%d 分钟）" % (DEEP_TIMEOUT_SEC // 60) if btimeout
                    else (str(e).strip() or "已取消")
                )
                ojob["finished"] = True
                ojob["progress"] = -1
    except Exception as e:
        logger.exception("深度分析失败 uid=%s gen=%s key=%s", nuid, ngen, skey)
        with deeplock:
            if DeepJobAlive(nuid, ngen):
                ojob = GetDeepJob(nuid)
                ojob["error"] = str(e)
                ojob["finished"] = True
                ojob["progress"] = -1
    finally:
        ReleaseLlm("deep", nuid)
        with deeplock:
            if DeepJobAlive(nuid, ngen):
                GetDeepJob(nuid)["running"] = False


def StartDeepAnalysis(oconfig, nfilename, sroot=None, skey=None, nuid=0):
    """启动深度分析。与「纳入研究 / 知识查询」共用同一把 LLM 互斥锁。"""
    with deeplock:
        if GetDeepJob(nuid).get("running"):
            return {"error": "深度分析正在进行中，请等待完成"}
    if not TryAcquireLlm("deep", skey or nfilename or "", nuid):
        return LlmBusyPayload(nuid) or {"error": "大模型正忙，请稍后再试"}
    ngen = BeginDeepJob(
        nuid,
        current=nfilename or skey or "",
        key=skey or "",
    )
    t = threading.Thread(
        target=_RunDeepJob,
        args=(oconfig, nfilename, sroot),
        kwargs={"skey": skey, "nuid": nuid, "ngen": ngen},
        daemon=True,
    )
    t.start()
    return {"status": "started", "file": nfilename or skey or ""}
