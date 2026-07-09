#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""纳入研究流水线：Prepare / LLM / Finalize 与后台任务。"""
import logging
import os
import uuid
import shutil
import concurrent.futures

import wiki_core as core
import topic_manager as topics
import wiki_refresh as refresh
import request_log
from io_utils import SafeName
from paper_io import ExtractPaperText
from paper_sections import PackForIngest
from llm_client import CallLlm, ParseLlmJson, IngestCancelled
from job_state import (
    GetIngestJob, IngestJobAlive, IsIngestCancelled,
    ReleaseLlm, TryAcquireLlm, ingestlock,
)
from app_scope import UserScope

logger = logging.getLogger(__name__)


def SafeWikiPath(nrelpath):
    """校验 LLM 返回的写入路径必须落在当前选题 wiki/ 目录内且为 .md 文件。"""
    nrelpath = nrelpath.replace("\\", "/").lstrip("/")
    if not nrelpath.endswith(".md") or ".." in nrelpath:
        return None
    nsub = nrelpath[5:] if nrelpath.startswith("wiki/") else nrelpath
    if not nsub:
        return None
    nwbase = os.path.normpath(core.wikidir)
    fullpath = os.path.normpath(os.path.join(nwbase, nsub))
    if not (fullpath == nwbase or fullpath.startswith(nwbase + os.sep)):
        return None
    return fullpath


def BuildIngestMessages(oconfig, nfilename, npapertext):
    """构造精简入库提示词：快速接入 wiki 网络（深度审计留给「深度研究」）。"""
    with open(topics.RulePath("purpose.md"), "r", encoding="utf-8") as f:
        spurposefull = f.read()
    purpose = spurposefull[:2800]
    ofields = topics.ParsePurposeFields(spurposefull)
    vrqlines = []
    for skey in ("rq1", "rq2", "rq3", "rq4"):
        sval = (ofields.get(skey) or "").strip()
        if sval and sval not in ("（待填写）", "（未填写）"):
            vrqlines.append(sval)
    srqctx = "\n".join(vrqlines) if vrqlines else "（尚未填写具体研究问题，请从 purpose 方向推断可能关联）"
    vnodes = refresh.GetWikiData()["nodes"]
    existing = "\n".join(
        "- %s (%s): %s" % (n["id"], n["type"], n.get("title", "")) for n in vnodes
    )[:2400]
    vrqpages = [n for n in vnodes if n.get("type") == "rq"]
    srqpages = "\n".join("- [[%s]]: %s" % (n["id"], n.get("title", "")) for n in vrqpages) or "（尚无研究问题页）"
    meta = core.ParseSourceFilename(nfilename)
    slang = oconfig.get("language", "中文")
    system = (
        "你是博士论文知识库的「入库编译引擎」。目标：快速把文献接入 wiki 网络，"
        "产出精简摘要与交叉链接。"
        "**不做**方法论审计、识别策略红队、跨文献长对比（这些留给后续的「深度研究」）。"
        "严格遵守：(1) YAML frontmatter 含 type/title/aliases/sources/tags/created/updated；"
        "source 页可含 url（DOI 优先）；(2) 用 [[wikilink]] 复用已有 id；"
        "(3) kebab-case 命名；(4) 只输出 JSON。"
        "用%s撰写。" % slang
    )
    user = (
        "## 论文目标 (purpose.md)\n%s\n\n"
        "## 当前研究问题（仅做标签式关联，不做论证级分析）\n%s\n\n"
        "## 已有 wiki 页面（复用 id）\n%s\n\n"
        "## 已有研究问题页\n%s\n\n"
        "## 待入库文献\n文件名：%s\n建议 key：%s\n正文(智能节选)：\n%s\n\n"
        "## 必须输出（精简）\n"
        "1. wiki/sources/<key>.md — 章节：\n"
        "   - ## 一句话概括（1 句）\n"
        "   - ## 研究问题（1–2 句）\n"
        "   - ## 方法与数据（3–5 句，不展开识别策略审计）\n"
        "   - ## 主要结论（2–3 句）\n"
        "   - ## 关联研究问题（列出 [[rq-...]]，一句话说明关联）\n"
        "   **禁止写**：长篇张力分析、可借鉴设计清单、方法论评级、跨文献对比表\n"
        "2. wiki/synthesis/<key>-memo.md — type:synthesis，3–5 句综述可用备忘\n"
        "3. wiki/concepts/ 2–3 个核心概念页（每页简短，相互链接）\n"
        "**不要输出** comparison 页；entity 页除非关键机构/数据集\n\n"
        "## 输出 JSON\n"
        '{\n'
        '  "key": "作者姓-年份",\n'
        '  "files": [{"path": "wiki/sources/<key>.md", "content": "..."}],\n'
        '  "log": "一句话操作摘要",\n'
        '  "review": ["需人工核实的点"],\n'
        '  "research": {\n'
        '    "rq_links": ["rq-..."],\n'
        '    "supports_thesis": "对论点一句话（可选）",\n'
        '    "synthesis_id": "<key>-memo"\n'
        '  }\n'
        '}\n'
        "source 页 sources 写 [%s]；不确定写入 review；尽量填 url。"
        % (purpose, srqctx, existing, srqpages, nfilename, meta["key"],
           PackForIngest(npapertext), meta["key"])
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def IngestPrepare(oconfig, nfilename, nuid=0, ngen=0):
    """摄入阶段一（文件读取，须在 UserScope 内）：提取文本并构造 LLM 消息。"""
    fullpath = os.path.join(core.rawsourcesdir, SafeName(nfilename))
    if not os.path.isfile(fullpath):
        raise FileNotFoundError(nfilename)
    if IsIngestCancelled(nuid, ngen):
        raise IngestCancelled("用户已取消")
    stext = ExtractPaperText(fullpath)
    if not stext.strip():
        raise ValueError("无法提取文本（可能是扫描版 PDF）")
    return BuildIngestMessages(oconfig, nfilename, stext)


def IngestFinalize(nfilename, content, nuid=0, ngen=0):
    """摄入阶段三（文件写入，须在 UserScope 内）：解析 LLM 输出，staging 后一次性 commit。"""
    if IsIngestCancelled(nuid, ngen):
        raise IngestCancelled("用户已取消")
    result = ParseLlmJson(content)
    vcommits = []
    sstaging = os.path.join(core.wikidir, ".ingest-staging", uuid.uuid4().hex)
    try:
        for item in result.get("files", []):
            if IsIngestCancelled(nuid, ngen):
                raise IngestCancelled("用户已取消")
            fp = SafeWikiPath(item.get("path", ""))
            body = item.get("content", "")
            if not fp or not body.strip():
                continue
            import wiki_markdown as md
            body = md.SanitizeFrontmatter(body)  # 修正 LLM 生成的非法 frontmatter（如 title 含冒号）
            srel = os.path.relpath(fp, core.wikidir)
            spart = os.path.join(sstaging, srel)
            os.makedirs(os.path.dirname(spart), exist_ok=True)
            import analysis_version as aver
            spipe = aver.PipelineForWikiPath(srel)
            if spipe:
                body = aver.StampMarkdown(body, spipe)
            with open(spart, "w", encoding="utf-8") as f:
                f.write(body)
            vcommits.append((spart, fp))
        if not vcommits:
            raise ValueError("LLM 未返回有效页面")
        vwritten = []
        for spart, fp in vcommits:
            os.makedirs(os.path.dirname(fp), exist_ok=True)
            os.replace(spart, fp)
            vwritten.append(os.path.relpath(fp, core.rootdir))
    finally:
        if os.path.isdir(sstaging):
            shutil.rmtree(sstaging, ignore_errors=True)
    skey = result.get("key") or core.ParseSourceFilename(nfilename)["key"]
    core.MergePendingUrlToSource(nfilename, skey)
    logmsg = result.get("log") or ("摄入 %s" % nfilename)
    review = result.get("review") or []
    oresearch = result.get("research") or {}
    if isinstance(oresearch, dict) and review and not oresearch.get("next_steps"):
        oresearch["next_steps"] = review[:3]
    core.AppendLog("[ingest] %s（新增 %d 页）%s" % (
        logmsg, len(vwritten), ("；待核实：" + "；".join(review)) if review else ""))
    import wiki_workflow as wflow
    wflow.Init(core.wikidir)
    sblurb = ""
    if isinstance(oresearch, dict):
        sblurb = (oresearch.get("supports_thesis") or "")[:120]
    orqsync = wflow.SyncRqPages(skey, oresearch, sblurb)
    return {
        "key": skey,
        "file": nfilename,
        "written": vwritten,
        "research": oresearch,
        "review": review,
        "rq_sync": orqsync,
    }


def RunIngestJob(oconfig, vtargets, sroot=None, nuid=0, ngen=0):
    """后台线程：逐篇摄入并实时更新 ingestjob 进度。"""
    logger.info("纳入研究开始 uid=%s gen=%s rid=%s targets=%d", nuid, ngen, request_log.CurrentId() or "-", len(vtargets or []))
    if not TryAcquireLlm("ingest", vtargets[0] if vtargets else "", nuid):
        with ingestlock:
            if IngestJobAlive(nuid, ngen):
                ojob = GetIngestJob(nuid)
                ojob["running"] = False
                ojob["finished"] = True
                ojob["failed"].append({
                    "file": "(忙碌)",
                    "error": "知识查询进行中，请稍后再纳入研究",
                })
        return
    oprefetch = {}
    oexecutor = concurrent.futures.ThreadPoolExecutor(max_workers=1)

    def StartPrefetch(snext):
        if not snext:
            return

        def _work():
            with UserScope(sroot):
                return IngestPrepare(oconfig, snext, nuid, ngen)

        oprefetch[snext] = oexecutor.submit(_work)

    try:
        for nidx, fn in enumerate(vtargets):
            with ingestlock:
                if not IngestJobAlive(nuid, ngen):
                    break
                ojob = GetIngestJob(nuid)
                if ojob.get("cancelled"):
                    break
                ojob["current"] = fn
            bbreak = False
            try:
                ofuture = oprefetch.pop(fn, None)
                if ofuture is not None:
                    vmessages = ofuture.result()
                else:
                    with UserScope(sroot):
                        vmessages = IngestPrepare(oconfig, fn, nuid, ngen)
                if nidx + 1 < len(vtargets):
                    StartPrefetch(vtargets[nidx + 1])
                fcancel = lambda: IsIngestCancelled(nuid, ngen)
                content = CallLlm(oconfig, vmessages, fcancel=fcancel)
                with UserScope(sroot):
                    oresult = IngestFinalize(fn, content, nuid, ngen)
                with ingestlock:
                    if IngestJobAlive(nuid, ngen):
                        ojob = GetIngestJob(nuid)
                        ojob["ingested"].append(fn)
                        if isinstance(oresult, dict) and oresult.get("research"):
                            ojob.setdefault("briefs", []).append({
                                "file": fn,
                                "key": oresult.get("key", ""),
                                "research": oresult.get("research", {}),
                                "review": oresult.get("review", []),
                            })
            except IngestCancelled:
                bbreak = True
                with ingestlock:
                    if IngestJobAlive(nuid, ngen):
                        GetIngestJob(nuid)["failed"].append({"file": fn, "error": "已取消"})
            except Exception as e:
                logger.exception("纳入研究失败 file=%s uid=%s gen=%s", fn, nuid, ngen)
                with ingestlock:
                    if IngestJobAlive(nuid, ngen):
                        GetIngestJob(nuid)["failed"].append({"file": fn, "error": str(e)})
            with ingestlock:
                if IngestJobAlive(nuid, ngen):
                    GetIngestJob(nuid)["done"] += 1
            if bbreak:
                break
        if not IsIngestCancelled(nuid, ngen):
            try:
                with UserScope(sroot):
                    refresh.RefreshWiki(bwrite_files=True, bforce=True)
            except Exception as e:
                logger.warning("纳入研究后刷新索引失败：%s", e)
                with ingestlock:
                    if IngestJobAlive(nuid, ngen):
                        GetIngestJob(nuid)["failed"].append(
                            {"file": "(刷新索引)", "error": str(e)})
    except Exception as e:
        logger.exception("纳入研究任务异常 uid=%s gen=%s", nuid, ngen)
        with ingestlock:
            if IngestJobAlive(nuid, ngen):
                GetIngestJob(nuid)["failed"].append({"file": "(任务异常)", "error": str(e)})
    finally:
        oexecutor.shutdown(wait=False)
        ReleaseLlm("ingest", nuid)
        with ingestlock:
            if IngestJobAlive(nuid, ngen):
                ojob = GetIngestJob(nuid)
                ojob["running"] = False
                ojob["finished"] = True
                ojob["current"] = ""
