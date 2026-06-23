#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""三阶段深度文献分析引擎。

阶段① 结构提取 → 阶段② 方法论深度分析 → 阶段③ 知识网络整合
输出：wiki/analysis/<key>-report.md（深度研究报告）
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


def _Now():
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d")


def _Truncate(s, n=120):
    return s[:n] + "…" if len(s) > n else s


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


def _ReadSourcePage(skey):
    """读取已生成的 source 页面正文作为 Stage 1 补充上下文。"""
    spath = os.path.join(core.wikidir, "sources", skey + ".md")
    if os.path.isfile(spath):
        with open(spath, "r", encoding="utf-8") as f:
            return f.read()
    return ""


# ---- Stage 1: 结构提取 ----
def _Stage1(oconfig, npapertext, skey, stitle):
    """提取论文结构：框架、方法、数据、结果、参考文献。"""
    system = (
        "你是论文结构分析引擎。从论文全文中提取关键结构信息，输出 JSON。"
        "不要摘抄，而是用简练的研究语言归纳。"
        "输出 JSON 对象，key 见 user 消息中的要求。"
    )
    user = (
        "## 论文\n标题：%s\n引用 key：%s\n\n全文：\n%s\n\n"
        "请输出 JSON，字段如下：\n"
        '{\n'
        '  "research_topic": "一句话研究主题",\n'
        '  "theoretical_tradition": "理论传统来源",\n'
        '  "core_argument": "核心论点的 2-3 句话归纳",\n'
        '  "hypothesis_chain": ["假设1", "假设2"],\n'
        '  "implicit_assumptions": ["隐含假设1"],\n'
        '  "identification_strategy": "详细说明识别策略（DID/RDD/IV/OLS 等），包含关键假设和检验方法",\n'
        '  "data_description": "数据来源、样本量、时间跨度、处理组/对照组规模",\n'
        '  "key_variables": [{"name":"变量名","type":"DV/IV/控制","measurement":"如何测量"}],\n'
        '  "main_results": [{"estimate":"核心估计系数","se":"标准误","significance":"显著水平"}],\n'
        '  "robustness_checks": ["稳健性检验1"],\n'
        '  "internal_validity": ["内部效度威胁与应对"],\n'
        '  "external_validity": "外部有效性边界的讨论",\n'
        '  "key_references": ["作者年份: 论文标题（被引位置概述）"],\n'
        '  "limitations": ["作者自述局限性"]\n'
        '}\n'
        "注意：如果某字段在论文中找不到明确信息，设为空字符串或空数组，不要臆造。"
        % (stitle, skey, npapertext[:22000])
    )
    content = CallLlm(oconfig, [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ], bjson=True, fcancel=IsIngestCancelled)
    return ParseLlmJson(content) if isinstance(content, str) else content


# ---- Stage 2: 方法论深度分析 ----
def _Stage2(oconfig, skey, stitle, ostruct, spurpose):
    """基于 Stage 1 结构做方法论批判性评估与 RQ 对齐。"""
    system = (
        "你是方法论评估专家。基于已提取的论文结构，给出深度分析方法论评价。"
        "重点在于发现论文的推理强度与弱点，而不是复述论文内容。"
        "输出 JSON 对象。"
    )
    sstruct = json.dumps(ostruct, ensure_ascii=False, indent=2)
    user = (
        "## 论文\n标题：%s\n引用 key：%s\n\n"
        "## 已提取结构\n%s\n\n"
        "## 当前研究目标 (purpose)\n%s\n\n"
        "请输出 JSON，字段说明：\n"
        '{\n'
        '  "methodology_rating": "评级（强/中等/偏弱）与一句话理由",\n'
        '  "design_strengths": ["研究设计的主要优势"],\n'
        '  "design_weaknesses": ["研究设计的主要弱点/缺陷"],\n'
        '  "identification_issues": "识别策略的潜在问题（平行趋势是否讨论、工具变量是否弱等）",\n'
        '  "measurement_validity": "核心变量的测量效度评价",\n'
        '  "alternative_explanations": ["可能的替代解释/混淆因素"],\n'
        '  "result_reliability": "结果可信度评价（标准误、多重比较、p-hacking 风险等）",\n'
        '  "rq_alignment": [{"rq":"RQ描述","alignment":"强相关/部分相关/弱相关","reason":"理由"}],\n'
        '  "thesis_implication": "对当前论文论点的含义（支撑/挑战/补充）",\n'
        '  "research_design_takeaways": ["可以从这篇论文借鉴的研究设计方案"]\n'
        '}\n'
        "分析要具体、有批判性，不空泛。"
        % (stitle, skey, sstruct[:8000], spurpose[:2000])
    )
    content = CallLlm(oconfig, [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ], bjson=True, fcancel=IsIngestCancelled)
    return ParseLlmJson(content) if isinstance(content, str) else content


# ---- Stage 3: 知识网络整合 ----
def _Stage3(oconfig, skey, stitle, ostruct, oanalysis, spurpose,
            sprior_sources, sconcepts, srqs):
    """整合已有知识库，生成最终研究报告。"""
    system = (
        "你是知识网络整合专家。基于论文结构提取结果和方法论分析，"
        "结合已有知识库，生成一份完整的深度研究报告 Markdown。"
        "直接输出 Markdown 正文（不含 YAML frontmatter），"
        "使用 [[wikilink]] 格式引用已有概念/文献。"
    )
    sstruct = json.dumps(ostruct, ensure_ascii=False, indent=2)[:4000]
    sanalysis = json.dumps(oanalysis, ensure_ascii=False, indent=2)[:4000]
    user = (
        "## 论文：%s（引用 key：%s）\n\n"
        "## 已提取结构\n%s\n\n"
        "## 方法论分析\n%s\n\n"
        "## 已有文献\n%s\n\n"
        "## 已有概念\n%s\n\n"
        "## 已有研究问题\n%s\n\n"
        "## 研究目标\n%s\n\n"
        "请生成一篇深度研究报告 Markdown。报告必须包含以下章节（用 ## 标题）：\n\n"
        "### 1. 论文定位与全景\n"
        "### 2. 理论基础与假设推演\n"
        "### 3. 方法论深度评估\n"
        "- 3.1 识别策略\n"
        "- 3.2 数据与样本\n"
        "- 3.3 关键变量测量\n"
        "- 3.4 内部效度威胁\n"
        "- 3.5 外部效度边界\n"
        "### 4. 核心实证结果解读\n"
        "### 5. 与当前研究问题的关系\n"
        "### 6. 跨文献对比\n"
        "### 7. 可借鉴的研究设计\n"
        "### 8. 关键引用网络\n"
        "### 9. 疑点与待核实项\n\n"
        "要求：\n"
        "- 每个章节内容充实、具体，不要留空\n"
        "- 跨文献对比部分要真实对比已有文献的内容（基于已有文献列表）\n"
        "- 引用已有文献/概念时用 [[wikilink]] 格式\n"
        "- 不臆造文献中不存在的内容\n"
        "- 语言专业但清晰"
        % (stitle, skey, sstruct, sanalysis,
           sprior_sources or "（无）", sconcepts or "（无）",
           srqs or "（无）", spurpose[:2000])
    )
    content = CallLlm(oconfig, [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ], bjson=False, fcancel=IsIngestCancelled)
    return content


# ---- 主流程 ----
def DeepAnalyzePaper(oconfig, nfilename, sroot=None):
    """三阶段深度分析主流程。"""
    if sroot:
        core.SetDataRoot(sroot)
        topics.Init(sroot)

    # 读取原始文件
    fullpath = os.path.join(core.rawsourcesdir, SafeName(nfilename))
    if not os.path.isfile(fullpath):
        raise FileNotFoundError("原始文件不存在：%s" % nfilename)
    update_callback(0, "准备")

    text = ExtractPaperText(fullpath)
    if not text.strip():
        raise ValueError("无法提取文本（可能是扫描版 PDF）")

    meta = core.ParseSourceFilename(nfilename)
    skey = meta["key"]
    stitle = meta.get("title") or skey

    spurpose = _ReadPurpose()
    sprior_sources, sconcepts, srqs, vnodes = _LoadExistingWikiContext()

    # 更新进度：阶段 1
    update_callback(1, "阶段① 结构提取")
    core.AppendLog("[deep] %s：阶段① 结构提取开始" % skey)
    ostruct = _Stage1(oconfig, text, skey, stitle)
    update_callback(30, "阶段② 方法论分析")

    # 阶段 2
    update_callback(2, "阶段② 方法论分析")
    core.AppendLog("[deep] %s：阶段② 方法论深度分析" % skey)
    oanalysis = _Stage2(oconfig, skey, stitle, ostruct, spurpose)
    update_callback(60, "阶段③ 报告生成")

    # 阶段 3
    update_callback(3, "阶段③ 报告生成")
    core.AppendLog("[deep] %s：阶段③ 知识网络整合（生成报告）" % skey)
    report_md = _Stage3(oconfig, skey, stitle, ostruct, oanalysis, spurpose,
                        sprior_sources, sconcepts, srqs)
    update_callback(95, "写入报告")

    # 生成 YAML frontmatter
    frontmatter = (
        "---\n"
        "type: analysis-report\n"
        "title: 深度研究报告 — %s\n"
        "sources: [%s]\n"
        "created: %s\n"
        "updated: %s\n"
        "---\n\n"
    ) % (stitle, skey, _Now(), _Now())

    full_report = frontmatter + "# 深度研究报告：%s\n\n> 本报告由 Agent 经三阶段分析生成。原始文献：[[%s]]\n\n" % (stitle, skey) + report_md

    # 写入文件
    analysis_dir = os.path.join(core.wikidir, "analysis")
    os.makedirs(analysis_dir, exist_ok=True)
    report_path = os.path.join(analysis_dir, "%s-report.md" % skey)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(full_report)

    core.AppendLog("[deep] %s：深度研究报告已生成（%s）" % (skey, os.path.relpath(report_path, core.rootdir)))
    core.GenerateIndex()
    update_callback(100)

    return {
        "key": skey,
        "file": nfilename,
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
    """获取深度分析任务状态（线程安全）。"""
    with deeplock:
        return dict(deepjob)


def _RunDeepJob(oconfig, nfilename, sroot=None):
    """后台执行深度分析，自动处理错误与状态更新。"""
    global update_callback
    update_callback = _DefaultUpdateCb
    try:
        with deeplock:
            deepjob["running"] = True
            deepjob["finished"] = False
            deepjob["progress"] = 0
            deepjob["stage"] = "准备"
            deepjob["current"] = nfilename
            deepjob["error"] = ""
            deepjob["result"] = None

        oresult = DeepAnalyzePaper(oconfig, nfilename, sroot)

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
        with deeplock:
            deepjob["running"] = False


def StartDeepAnalysis(oconfig, nfilename, sroot=None):
    """启动后台深度分析工作线程。"""
    global deepjob
    with deeplock:
        if deepjob.get("running"):
            return {"error": "深度分析正在进行中，请等待完成"}
        deepjob = {
            "running": True,
            "finished": False,
            "progress": 0,
            "current": nfilename,
            "error": "",
            "result": None,
            "stage": "准备",
        }
    t = threading.Thread(target=_RunDeepJob, args=(oconfig, nfilename, sroot), daemon=True)
    t.start()
    return {"status": "started", "file": nfilename}
