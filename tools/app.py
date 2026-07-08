#!/usr/bin/env python3
"""研栈本地服务：在网页里完成 添加 / 分析 / 删除 / 刷新。

启动：
    python3 tools/app.py
然后浏览器访问 http://127.0.0.1:8765 （启动器会自动打开）。

新用户默认使用内置智谱 GLM-4-Flash；也可在「偏好设置」中替换为自己的 API。
未配置且无内置 Key 时返回 need_key，网页会提示并打开设置。
"""

import os
import sys
import json
import time
import uuid
import base64
import logging
import threading
import subprocess
import webbrowser
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

logger = logging.getLogger(__name__)

import wiki_core as core
import topic_manager as topics
import wiki_ops as wops
import doc_editor as doced
import onboarding as onboard
import builtin_llm as bllm
import auth
from app_meta import APP_NAME, ResolveConfigDir
from contextlib import contextmanager
from io_utils import AtomicWriteJson, AtomicWriteText, SafeName
from llm_client import (
    CallLlm, CallLlmStream, HasUsableApiKey, IngestCancelled, IsPlaceholderApiKey,
    ParseLlmJson, apikeymask,
)
from job_state import (
    BeginIngestJob, BeginQueryJob, GetIngestJob, GetQueryJob,
    IngestJobAlive, IsIngestCancelled, LlmBusyPayload, QueryJobAlive,
    ReleaseLlm, TryAcquireLlm, ingest_active_uid, query_active_uid,
    ingestlock, querylock,
)
from paper_io import ExtractPaperText
from paper_sections import PackForIngest
import research_deep as rdeep
import bib_io
import concurrent.futures
import research_standard as rstd
import wiki_refresh as refresh

host = "127.0.0.1"
port = 8765
desktopmode = False  # desktop.py 启动时设为 True，界面走桌面模式（服务开关控制功能而非关进程）
desktop_pick_folder = None  # desktop.py 注入：主线程弹出文件夹选择框（备用）
multiuser = False  # tools/server.py（云端部署）设为 True：登录 + 每用户数据隔离
llmdailylimit = 0  # 多用户模式下每用户每日 LLM 调用上限（0 = 不限）
baseroot = core.rootdir  # 主项目根（templates 来源）
configdir = ResolveConfigDir(core.rootdir)
configpath = os.path.join(configdir, "config.json")

# 多用户数据根绑定：所有文件操作（请求处理 + 后台任务的读写阶段）都必须
# 先 BindDataRoot 再操作；datalock 保证同一时刻只有一个绑定生效。
# LLM 网络调用（耗时数分钟）在锁外进行，不阻塞其他用户的请求。
datalock = threading.RLock()
_boundroot = core.rootdir


def BindDataRoot(nroot):
    """切换全局数据根（须在 datalock 内调用）。单用户模式下恒为项目根。"""
    global configdir, configpath, _boundroot
    if not nroot or nroot == _boundroot:
        return
    topics.Init(nroot)
    core.rootdir = nroot
    core.ReloadTopicPaths()
    refresh.InvalidateWikiCache()
    configdir = ResolveConfigDir(nroot)
    configpath = os.path.join(configdir, "config.json")
    _boundroot = nroot


@contextmanager
def UserScope(nroot=None):
    """请求 / 后台任务的文件操作临界区：持锁 + 绑定数据根。"""
    datalock.acquire()
    try:
        if multiuser and nroot:
            BindDataRoot(nroot)
        yield
    finally:
        datalock.release()

# PDF 静态服务大小上限（150MB）
pdf_max_serve_bytes = 150 * 1024 * 1024
pdf_serve_chunk = 256 * 1024
max_body_bytes = 160 * 1024 * 1024
max_upload_bytes = 150 * 1024 * 1024
_exportdir_cache = {}


def PickFolderNative():
    """系统原生文件夹选择（可从 HTTP 工作线程安全调用）。"""
    if desktopmode and desktop_pick_folder:
        try:
            spath = desktop_pick_folder()
            if spath:
                return spath.rstrip("/\\")
        except Exception:
            pass
    if sys.platform == "darwin":
        try:
            r = subprocess.run(
                ["osascript", "-e", 'POSIX path of (choose folder with prompt "选择导出文件夹")'],
                capture_output=True,
                text=True,
                timeout=300,
            )
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.strip().rstrip("/")
        except Exception:
            pass
    if sys.platform.startswith("win"):
        try:
            scmd = (
                "Add-Type -AssemblyName System.windows.forms; "
                "$d=New-Object System.Windows.Forms.FolderBrowserDialog; "
                "$d.Description='选择导出文件夹'; "
                "if($d.ShowDialog() -eq 'OK'){Write-Output $d.SelectedPath}"
            )
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Sta", "-Command", scmd],
                capture_output=True,
                text=True,
                timeout=300,
            )
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.strip().rstrip("\\/")
        except Exception:
            pass
    try:
        r = subprocess.run(
            ["zenity", "--file-selection", "--directory", "--title=选择导出文件夹"],
            capture_output=True,
            text=True,
            timeout=300,
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip().rstrip("/")
    except Exception:
        pass
    sscript = (
        "import tkinter as tk\n"
        "from tkinter import filedialog\n"
        "r=tk.Tk()\n"
        "r.withdraw()\n"
        "try:\n"
        "    r.attributes('-topmost', True)\n"
        "except Exception:\n"
        "    pass\n"
        "p=filedialog.askdirectory(title='选择导出文件夹')\n"
        "r.destroy()\n"
        "print(p or '', end='')\n"
    )
    try:
        r = subprocess.run(
            [sys.executable, "-c", sscript],
            capture_output=True,
            text=True,
            timeout=300,
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip().rstrip("/\\")
    except Exception:
        pass
    if desktop_pick_folder:
        try:
            return desktop_pick_folder() or ""
        except Exception:
            pass
    return ""


VALID_THEMES = frozenset({"fresh", "girly", "boyish", "cool"})


def NormalizeTheme(stheme):
    sid = (stheme or "").strip()
    return sid if sid in VALID_THEMES else "girly"


def ConfigDefaults():
    return {
        "base_url": "https://api.openai.com/v1",
        "api_key": "",
        "model": "gpt-4o-mini",
        "language": "中文",
        "theme": "girly",
    }


def LoadConfigRaw():
    if os.path.isfile(configpath):
        try:
            with open(configpath, "r", encoding="utf-8") as f:
                odata = json.load(f)
                if isinstance(odata, dict):
                    return odata
        except Exception as e:
            logger.warning("读取 config.json 失败，将使用默认配置：%s", e)
    return {}


def ApplyConfigDefaults(oraw):
    ocfg = ConfigDefaults()
    if oraw:
        ocfg.update(oraw)
    if "theme" in ocfg:
        ocfg["theme"] = NormalizeTheme(ocfg.get("theme"))
    return ocfg


def LoadConfig():
    ocfg = ApplyConfigDefaults(LoadConfigRaw())
    omerged, _ = bllm.ApplyBuiltinLlm(ocfg, HasUsableApiKey)
    return omerged


def GetConfigForApi():
    ocfg = ApplyConfigDefaults(LoadConfigRaw())
    omerged, busing = bllm.ApplyBuiltinLlm(ocfg, HasUsableApiKey)
    return {
        "base_url": omerged.get("base_url"),
        "model": omerged.get("model"),
        "language": omerged.get("language"),
        "theme": omerged.get("theme"),
        "has_api_key": HasUsableApiKey(omerged),
        "using_builtin_llm": busing,
        "api_key": "",
    }


def GetUserTheme():
    return NormalizeTheme(LoadConfig().get("theme"))


def SaveConfig(oconfig):
    os.makedirs(configdir, exist_ok=True)
    merged = ApplyConfigDefaults(LoadConfigRaw())
    for skey in ("base_url", "model", "language", "theme"):
        if skey in oconfig:
            merged[skey] = oconfig[skey]
    if "theme" in merged:
        merged["theme"] = NormalizeTheme(merged.get("theme"))
    if oconfig.get("clear_api_key"):
        merged["api_key"] = ""
        if "pollinations.ai" in (merged.get("base_url") or ""):
            merged["use_builtin_llm"] = False
    elif "api_key" in oconfig:
        snewkey = (oconfig.get("api_key") or "").strip()
        if not IsPlaceholderApiKey(snewkey):
            merged["api_key"] = snewkey
            merged["use_builtin_llm"] = False
    if oconfig.get("use_builtin_llm") is False:
        merged["use_builtin_llm"] = False
    opersist = {k: v for k, v in merged.items() if not str(k).startswith("_")}
    AtomicWriteJson(configpath, opersist)
    return LoadConfig()


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
    lang = oconfig.get("language", "中文")
    system = (
        "你是博士论文知识库的「入库编译引擎」。目标：快速把文献接入 wiki 网络，"
        "产出精简摘要与交叉链接。"
        "**不做**方法论审计、识别策略红队、跨文献长对比（这些留给后续的「深度研究」）。"
        "严格遵守：(1) YAML frontmatter 含 type/title/aliases/sources/tags/created/updated；"
        "source 页可含 url（DOI 优先）；(2) 用 [[wikilink]] 复用已有 id；"
        "(3) kebab-case 命名；(4) 只输出 JSON。"
        "用%s撰写。" % lang
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
    text = ExtractPaperText(fullpath)
    if not text.strip():
        raise ValueError("无法提取文本（可能是扫描版 PDF）")
    return BuildIngestMessages(oconfig, nfilename, text)


def IngestFinalize(nfilename, content, nuid=0, ngen=0):
    """摄入阶段三（文件写入，须在 UserScope 内）：解析 LLM 输出，staging 后一次性 commit。"""
    import shutil
    import uuid

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


def RunQueryJob(oconfig, squestion, bsave, sroot=None, nuid=0, ngen=0):
    """后台线程：知识库问答，不阻塞网页其他操作。文件读写阶段绑定提交者的数据根。"""
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


def RunIngestJob(oconfig, vtargets, sroot=None, nuid=0, ngen=0):
    """后台线程：逐篇摄入并实时更新 ingestjob 进度。

    收尾逻辑放在 finally，保证无论中途发生何种异常，running 都会被置为 False，
    避免打包（无终端/证书等差异）环境下线程半途崩溃导致前端「一直转圈」。
    文件读写阶段绑定提交者的数据根（LLM 网络调用在锁外，不阻塞其他用户）。
    """
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


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8", vheaders=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for skey, sval in (vheaders or []):
            self.send_header(skey, sval)
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length > max_body_bytes:
            raise ValueError("请求体过大（上限 %d MB）" % (max_body_bytes // (1024 * 1024)))
        return json.loads(self.rfile.read(length).decode("utf-8")) if length else {}

    # ---------- 多用户：会话与认证 ----------

    def _SessionUser(self):
        return auth.ResolveSession(auth.CookieFromHeaders(self.headers.get("Cookie", "")))

    def _AuthGet(self, path):
        """多用户模式下的 GET 认证网关。返回 True 表示已应答。"""
        if path == "/login":
            self._send(200, auth.LOGIN_HTML, "text/html; charset=utf-8")
            return True
        if path == "/auth/me":
            ouser = self._SessionUser()
            self._send(200, {"username": ouser["username"] if ouser else ""})
            return True
        ouser = self._SessionUser()
        if not ouser:
            if path in ("/", "/index.html"):
                self._send(200, auth.LOGIN_HTML, "text/html; charset=utf-8")
            else:
                self._send(401, {"error": "未登录，请刷新页面重新登录"})
            return True
        self._user = ouser
        return False

    def _RequestSecure(self):
        return self.headers.get("X-Forwarded-Proto", "").lower() == "https"

    def _AuthPost(self):
        """多用户模式下的 POST 认证网关。返回 True 表示已应答。"""
        if self.path == "/auth/register":
            body = self._body()
            try:
                auth.Register(body.get("username", ""), body.get("password", ""))
                stoken = auth.Login(body.get("username", ""), body.get("password", ""),
                                    self.client_address[0])
            except ValueError as e:
                self._send(200, {"error": str(e)})
                return True
            self._send(200, {"status": "ok"},
                       vheaders=[("Set-Cookie", auth.MakeSetCookie(stoken, bsecure=self._RequestSecure()))])
            return True
        if self.path == "/auth/login":
            body = self._body()
            try:
                stoken = auth.Login(body.get("username", ""), body.get("password", ""),
                                    self.client_address[0])
            except ValueError as e:
                self._send(200, {"error": str(e)})
                return True
            self._send(200, {"status": "ok"},
                       vheaders=[("Set-Cookie", auth.MakeSetCookie(stoken, bsecure=self._RequestSecure()))])
            return True
        if self.path == "/auth/logout":
            auth.Logout(auth.CookieFromHeaders(self.headers.get("Cookie", "")))
            self._send(200, {"status": "ok"},
                       vheaders=[("Set-Cookie", auth.MakeSetCookie("", bclear=True, bsecure=self._RequestSecure()))])
            return True
        ouser = self._SessionUser()
        if not ouser:
            self._send(401, {"error": "未登录，请刷新页面重新登录"})
            return True
        self._user = ouser
        if self.path in ("/api/shutdown", "/api/open/pdf", "/api/open/url", "/api/docs/pick-folder"):
            self._send(403, {"error": "云端多用户模式不支持此操作"})
            return True
        return False

    def _Uid(self):
        ouser = getattr(self, "_user", None)
        return ouser["uid"] if ouser else 0

    def _CheckLlmQuota(self, ncalls):
        """多用户模式：使用共享内置 Key 时的每日限额。返回错误提示或空串。"""
        if not multiuser or llmdailylimit <= 0:
            return ""
        oraw = ApplyConfigDefaults(LoadConfigRaw())
        if HasUsableApiKey(oraw):
            return ""  # 用户配置了自己的 Key，不限额
        if not auth.CheckAndCountLlm(self._Uid(), ncalls, llmdailylimit):
            return ("今日共享模型额度已用完（%d 次/天）。"
                    "可在「偏好设置」填写自己的免费 API Key（如智谱），不受限额。" % llmdailylimit)
        return ""

    def _CheckCsrf(self):
        if not multiuser:
            return True
        stoken = auth.CookieFromHeaders(self.headers.get("Cookie", ""))
        if not auth.VerifyCsrf(stoken, self.headers.get("X-Yz-CSRF", "")):
            self._send(403, {"error": "CSRF 校验失败，请刷新页面后重试"})
            return False
        return True

    def _BusyOwnerUid(self, sbusy):
        """返回当前占用某类 LLM 任务的用户 uid（多用户隔离用）。"""
        if sbusy == "ingest":
            with ingestlock:
                return GetIngestJob(ingest_active_uid).get("uid")
        if sbusy == "query":
            with querylock:
                return GetQueryJob(query_active_uid).get("uid")
        if sbusy == "deep":
            return rdeep.GetDeepActiveUid()
        if sbusy == "standard":
            return rstd.GetStandardActiveUid()
        return None

    def _MaybeOtherUserBusy(self, obusy):
        """多用户模式下，若占用者是其他用户，替换为通用「他人任务」提示。"""
        if not obusy or not multiuser:
            return obusy
        if self._BusyOwnerUid(obusy.get("busy")) not in (0, None, self._Uid()):
            return {"status": "busy", "busy": obusy.get("busy"),
                    "message": "服务器正在处理其他用户的任务，请稍后再试。"}
        return obusy

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if multiuser and self._AuthGet(path):
            return
        ouser = getattr(self, "_user", None)
        with UserScope(ouser["root"] if ouser else None):
            return self._HandleGet(path)

    def do_POST(self):
        if multiuser and self._AuthPost():
            return
        ouser = getattr(self, "_user", None)
        with UserScope(ouser["root"] if ouser else None):
            return self._HandlePost()

    def _HandleGet(self, path):
        if path in ("/", "/index.html"):
            ouser = getattr(self, "_user", None)
            stoken = auth.CookieFromHeaders(self.headers.get("Cookie", "")) if multiuser else ""
            odata = refresh.RefreshWiki(bwrite_files=True)
            return self._send(200, core.Render(
                odata, servermode=True, desktopmode=desktopmode,
                stheme=GetUserTheme(), susername=ouser["username"] if ouser else "",
                bcloud=multiuser, scsrf=auth.IssueCsrf(stoken) if stoken else "",
            ), "text/html; charset=utf-8")
        if path == "/api/data":
            return self._send(200, refresh.RefreshWiki(bwrite_files=True))
        if path == "/api/config":
            return self._send(200, GetConfigForApi())
        if path == "/api/ingest/progress":
            with ingestlock:
                ojob = GetIngestJob(self._Uid())
                return self._send(200, {k: v for k, v in ojob.items() if k not in ("uid", "gen")})
        if path == "/api/deep/progress":
            ostatus = rdeep.GetDeepJobStatus(self._Uid())
            return self._send(200, {k: v for k, v in ostatus.items() if k not in ("uid", "gen", "started_at")})
        if path == "/api/standard/progress":
            ostatus = rstd.GetStandardJobStatus(self._Uid())
            return self._send(200, {k: v for k, v in ostatus.items() if k not in ("uid", "gen", "started_at")})
        if path == "/api/query/progress":
            with querylock:
                ojob = GetQueryJob(self._Uid())
                return self._send(200, {k: v for k, v in ojob.items() if k not in ("uid", "gen")})
        if path == "/api/onboarding":
            return self._send(200, onboard.GetState())
        if path == "/api/lint":
            wops.Init(core.wikidir, core.rawsourcesdir, core.rootdir)
            return self._send(200, wops.RunLint())
        if path == "/api/chapters":
            import wiki_workflow as wflow
            wflow.Init(core.wikidir)
            return self._send(200, wflow.GetChapterProgress(refresh.GetWikiData()))
        if path == "/api/search":
            import urllib.parse
            import wiki_workflow as wflow
            wflow.Init(core.wikidir)
            oq = urllib.parse.parse_qs(self.path.split("?", 1)[-1] if "?" in self.path else "")
            sq = (oq.get("q") or [""])[0]
            return self._send(200, {"results": wflow.SearchWikiPages(sq)})
        if path == "/api/page":
            import urllib.parse
            oq = urllib.parse.parse_qs(self.path.split("?", 1)[-1] if "?" in self.path else "")
            sid = (oq.get("id") or [""])[0].strip()
            opage = core.GetPageContent(sid)
            if not opage:
                return self._send(404, {"error": "页面不存在"})
            return self._send(200, opage)
        if path == "/api/export/bibtex":
            wops.Init(core.wikidir, core.rawsourcesdir, core.rootdir)
            return self._send(200, {"bibtex": wops.ExportBibtex()})
        if path == "/api/sources/citations":
            wops.Init(core.wikidir, core.rawsourcesdir, core.rootdir)
            return self._send(200, {"citations": bib_io.ListCitations(refresh.GetWikiData())})
        if path == "/api/library/groups":
            return self._send(200, core.BuildLibraryGroups(refresh.GetWikiData()["nodes"]))
        if path == "/api/topics":
            return self._send(200, {
                "topics": core.TopicsWithCounts(),
                "current": topics.GetCurrentTopicId(),
                "purpose_fields": topics.GetPurposeFieldDefs(),
            })
        if path == "/api/rules":
            return self._send(200, topics.GetRules())
        if path == "/api/topics/config":
            import urllib.parse
            oquery = urllib.parse.parse_qs(self.path.split("?", 1)[-1] if "?" in self.path else "")
            nid = (oquery.get("id") or [""])[0]
            try:
                return self._send(200, topics.GetTopicConfig(nid))
            except ValueError as e:
                return self._send(400, {"error": str(e)})
        if path.startswith("/raw/sources/"):
            return self._serve_file(path)
        if path == "/api/docs":
            doced.Init(topics.GetTopicDir())
            import urllib.parse
            oq = urllib.parse.parse_qs(self.path.split("?", 1)[-1] if "?" in self.path else "")
            return self._send(200, doced.ListDocs((oq.get("tag") or [None])[0]))
        if path == "/api/docs/detail":
            import urllib.parse
            oq = urllib.parse.parse_qs(self.path.split("?", 1)[-1] if "?" in self.path else "")
            sid = (oq.get("id") or [""])[0]
            blight = (oq.get("light") or ["0"])[0] in ("1", "true", "yes")
            doced.Init(topics.GetTopicDir())
            try:
                return self._send(200, doced.GetDocDetail(sid, blight))
            except ValueError as e:
                return self._send(400, {"error": str(e)})
        if path == "/api/docs/preview":
            import urllib.parse
            oq = urllib.parse.parse_qs(self.path.split("?", 1)[-1] if "?" in self.path else "")
            sid = (oq.get("id") or [""])[0]
            doced.Init(topics.GetTopicDir())
            return self._send(200, doced.GetPreviewHtml(sid), "text/html; charset=utf-8")
        if path == "/api/docs/editor":
            return self._servedoceditor()
        if path == "/api/docs/media":
            return self._servedocmedia()
        if path == "/api/docs/revisions":
            import urllib.parse
            oq = urllib.parse.parse_qs(self.path.split("?", 1)[-1] if "?" in self.path else "")
            sid = (oq.get("id") or [""])[0]
            doced.Init(topics.GetTopicDir())
            return self._send(200, doced.ListRevisions(sid))
        if path == "/api/docs/revision":
            import urllib.parse
            oq = urllib.parse.parse_qs(self.path.split("?", 1)[-1] if "?" in self.path else "")
            sid = (oq.get("id") or [""])[0]
            srev = (oq.get("rev") or [""])[0]
            doced.Init(topics.GetTopicDir())
            return self._send(200, doced.GetRevisionDetail(sid, srev))
        if path == "/api/docs/status":
            import urllib.parse
            oq = urllib.parse.parse_qs(self.path.split("?", 1)[-1] if "?" in self.path else "")
            sid = (oq.get("id") or [""])[0]
            doced.Init(topics.GetTopicDir())
            return self._send(200, doced.GetWorkingStatus(sid))
        if path == "/api/docs/compare":
            import urllib.parse
            oq = urllib.parse.parse_qs(self.path.split("?", 1)[-1] if "?" in self.path else "")
            sid = (oq.get("id") or [""])[0]
            srev_a = (oq.get("a") or ["WORKING"])[0]
            srev_b = (oq.get("b") or [""])[0]
            doced.Init(topics.GetTopicDir())
            if not srev_b:
                shead = doced._HeadRevisionId(sid)
                srev_b = shead if shead else "original"
            return self._send(200, doced.CompareRevisions(sid, srev_a, srev_b))
        if path == "/api/docs/download":
            return self._docsdownload()
        return self._send(404, {"error": "not found"})

    def _servedoceditor(self):
        import urllib.parse
        oq = urllib.parse.parse_qs(self.path.split("?", 1)[-1] if "?" in self.path else "")
        sid = (oq.get("id") or [""])[0]
        stheme = (oq.get("theme") or ["girly"])[0]
        doced.Init(topics.GetTopicDir())
        try:
            return self._send(200, doced.GetEditorHtml(sid, stheme), "text/html; charset=utf-8")
        except Exception as e:
            smsg = str(e).replace("&", "&amp;").replace("<", "&lt;")
            if isinstance(e, ModuleNotFoundError) and "docx" in str(e):
                spy = "%d.%d.%d" % sys.version_info[:3]
                sexe = (sys.executable or "?").replace("&", "&amp;").replace("<", "&lt;")
                shint = (
                    '服务器缺少 <code>python-docx</code> 依赖。注意：Web 进程实际运行的是 '
                    '<b>Python %s</b>（解释器 <code>%s</code>），'
                    '请确认你安装 python-docx 时用的是<strong>同一个版本</strong>。'
                    '<br>若 Web 应用配置了 <b>virtualenv</b>，须在该 virtualenv 内安装：'
                    '<code>pip install python-docx</code>；'
                    '否则执行 <code>python%s -m pip install --user python-docx</code>，'
                    '然后到 Web 页点 <b>Reload</b> 再打开。'
                    % (spy, sexe, spy.rsplit(".", 1)[0])
                )
            else:
                shint = "请尝试重新导入 docx，或重启应用后再打开。"
            shtml = (
                '<!DOCTYPE html><html><head><meta charset="utf-8">'
                '<style>body{font-family:-apple-system,sans-serif;padding:40px;color:#4a3f47;background:#f8f6f4}'
                'h2{font-size:16px;margin-bottom:12px}.meta{font-size:13px;color:#8a7a84;line-height:1.7}'
                'code{background:#efe7e3;padding:1px 6px;border-radius:5px;font-size:12px}</style></head>'
                '<body><h2>文档编辑器加载失败</h2>'
                '<p class="meta">' + smsg + '</p>'
                '<p class="meta">' + shint + '</p></body></html>'
            )
            return self._send(500, shtml, "text/html; charset=utf-8")

    def _servedocmedia(self):
        import urllib.parse
        oq = urllib.parse.parse_qs(self.path.split("?", 1)[-1] if "?" in self.path else "")
        sid = (oq.get("id") or [""])[0]
        sfname = (oq.get("file") or oq.get("f") or [""])[0]
        doced.Init(topics.GetTopicDir())
        try:
            bdata, omime = doced.GetMediaBytes(sid, sfname)
        except Exception as e:
            return self._send(404, {"error": str(e)})
        self.send_response(200)
        self.send_header("Content-Type", omime)
        self.send_header("Content-Length", str(len(bdata)))
        self.end_headers()
        self.wfile.write(bdata)

    def _serve_file(self, path):
        import urllib.parse
        rel = urllib.parse.unquote(path.lstrip("/"))
        if not rel.startswith("raw/sources/"):
            return self._send(404, {"error": "file not found"})
        nfilename = rel.split("raw/sources/", 1)[1]
        full = os.path.normpath(os.path.join(core.rawsourcesdir, nfilename))
        if not full.startswith(os.path.normpath(core.rawsourcesdir)) or not os.path.isfile(full):
            return self._send(404, {"error": "file not found"})
        nsize = os.path.getsize(full)
        if nsize > pdf_max_serve_bytes:
            return self._send(413, {"error": "文件过大（上限 %d MB）" % (pdf_max_serve_bytes // (1024 * 1024))})
        ctype = "application/pdf" if full.lower().endswith(".pdf") else "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(nsize))
        if full.lower().endswith(".pdf"):
            self.send_header("Content-Disposition", 'inline; filename="%s"' % os.path.basename(full))
        self.end_headers()
        with open(full, "rb") as f:
            while True:
                bchunk = f.read(pdf_serve_chunk)
                if not bchunk:
                    break
                self.wfile.write(bchunk)

    def _HandlePost(self):
        self.path = self.path.split("?", 1)[0]
        if multiuser and not self.path.startswith("/auth/") and not self._CheckCsrf():
            return
        try:
            if self.path == "/api/upload":
                return self._upload()
            if self.path == "/api/delete":
                return self._delete()
            if self.path == "/api/ingest":
                return self._ingest()
            if self.path == "/api/ingest/deep":
                return self._deep_analyze()
            if self.path == "/api/ingest/standard":
                return self._standard_analyze()
            if self.path == "/api/config":
                body = self._body()
                SaveConfig(body)
                return self._send(200, {"status": "ok"})
            if self.path == "/api/shutdown":
                return self._shutdown()
            if self.path == "/api/topics/switch":
                return self._topicswitch()
            if self.path == "/api/topics/new":
                return self._topicnew()
            if self.path == "/api/topics/reset":
                return self._topicreset()
            if self.path == "/api/rules/save":
                return self._rulessave()
            if self.path == "/api/open/pdf":
                return self._openpdf()
            if self.path == "/api/open/url":
                return self._openurl()
            if self.path == "/api/source/url":
                return self._sourceurl()
            if self.path == "/api/source/tags":
                return self._sourcetags()
            if self.path == "/api/library/assign":
                return self._libraryassign()
            if self.path == "/api/ingest/cancel":
                return self._ingestcancel()
            if self.path == "/api/query":
                return self._query()
            if self.path == "/api/lint/fix":
                wops.Init(core.wikidir, core.rawsourcesdir, core.rootdir)
                return self._send(200, wops.FixLintIssues())
            if self.path == "/api/import/bibtex":
                return self._importbibtex()
            if self.path == "/api/topics/snapshot":
                return self._topicsnapshot()
            if self.path == "/api/onboarding/setup":
                return self._onboardingsetup()
            if self.path == "/api/onboarding/dismiss":
                return self._onboardingdismiss()
            if self.path == "/api/docs/import":
                return self._docsimport()
            if self.path == "/api/docs/meta":
                return self._docsmeta()
            if self.path == "/api/docs/extract":
                return self._docsextract()
            if self.path == "/api/docs/todo":
                return self._docstodo()
            if self.path == "/api/docs/edit":
                return self._docsedit()
            if self.path == "/api/docs/save":
                return self._docssave()
            if self.path == "/api/docs/restore":
                return self._docsrestore()
            if self.path == "/api/docs/restore-working":
                return self._docsrestoreworking()
            if self.path == "/api/docs/discard":
                return self._docsdiscard()
            if self.path == "/api/docs/export":
                return self._docsexport()
            if self.path == "/api/docs/pick-folder":
                return self._docspickfolder()
            if self.path == "/api/docs/delete":
                return self._docsdelete()
            return self._send(404, {"error": "not found"})
        except ValueError as e:
            if "请求体过大" in str(e):
                return self._send(413, {"error": str(e)})
            return self._send(400, {"error": str(e)})
        except Exception as e:
            logger.exception("POST %s 失败", self.path)
            if multiuser:
                return self._send(500, {"error": "服务器内部错误"})
            return self._send(500, {"error": str(e)})

    def _topicswitch(self):
        body = self._body()
        try:
            result = topics.SwitchTopic(body.get("id", ""))
        except ValueError as e:
            return self._send(400, {"error": str(e)})
        refresh.InvalidateWikiCache()
        core.ReloadTopicPaths()
        refresh.RefreshWiki(bwrite_files=True)
        return self._send(200, result)

    def _topicnew(self):
        body = self._body()
        try:
            result = topics.CreateTopic(
                body.get("name", "新选题"),
                body.get("fields"),
                True,
                body.get("import_from"),
            )
        except ValueError as e:
            return self._send(400, {"error": str(e)})
        refresh.InvalidateWikiCache()
        core.ReloadTopicPaths()
        refresh.RefreshWiki(bwrite_files=True)
        nqc = result.get("inherited_queries") or 0
        if nqc:
            core.AppendLog("新建选题：%s（%s），继承问答库 %d 页" % (
                result.get("name"), result.get("id"), nqc))
        else:
            core.AppendLog("新建选题：%s（%s）" % (result.get("name"), result.get("id")))
        return self._send(200, result)

    def _topicreset(self):
        result = topics.ResetCurrentTopic()
        refresh.InvalidateWikiCache()
        core.ReloadTopicPaths()
        refresh.RefreshWiki(bwrite_files=True)
        core.AppendLog("重置选题：%s" % result.get("name"))
        return self._send(200, result)

    def _onboardingsetup(self):
        body = self._body()
        result = onboard.SetupFromTitle(body.get("title", ""))
        core.ReloadTopicPaths()
        return self._send(200, result)

    def _onboardingdismiss(self):
        body = self._body()
        stype = body.get("type", "checklist")
        if stype == "welcome":
            result = onboard.DismissWelcome()
        else:
            result = onboard.DismissChecklist()
        return self._send(200, result)

    def _rulessave(self):
        body = self._body()
        skey = body.get("key", "")
        import wiki_workflow as wflow
        sold_fields = {}
        if skey == "purpose":
            sold_fields = topics.ParsePurposeFields(topics.ReadText(topics.RulePath("purpose.md")))
        topics.SaveRule(skey, content=body.get("content"), ofields=body.get("fields"))
        refresh.InvalidateWikiCache(core.wikidir)
        oresult = {"status": "ok"}
        if skey == "purpose" and body.get("fields"):
            vstale = wflow.DetectStaleSources(sold_fields, body.get("fields"))
            if vstale:
                oresult["stale_sources"] = vstale
                oresult["stale_hint"] = "研究问题或论点已变更，以下 %d 篇文献可能需要重新标准/深度分析" % len(vstale)
        return self._send(200, oresult)

    def _openpdf(self):
        """桌面端 QWebEngine 内嵌 iframe 无法正常预览 PDF，改由系统浏览器打开。"""
        import urllib.parse
        body = self._body()
        nfilename = SafeName(body.get("rawfile", ""))
        if not nfilename:
            return self._send(400, {"error": "缺少文件名"})
        nfull = os.path.normpath(os.path.join(core.rawsourcesdir, nfilename))
        if not nfull.startswith(os.path.normpath(core.rawsourcesdir)) or not os.path.isfile(nfull):
            return self._send(404, {"error": "PDF 不存在"})
        nurl = "http://%s:%d/raw/sources/%s" % (host, port, urllib.parse.quote(nfilename))
        webbrowser.open(nurl)
        return self._send(200, {"status": "ok", "url": nurl})

    def _openurl(self):
        """桌面端 QWebEngine 不跳转外部链接，改由系统浏览器打开。"""
        body = self._body()
        try:
            nurl = core.NormalizeUrl(body.get("url", ""))
        except ValueError as e:
            return self._send(400, {"error": str(e)})
        webbrowser.open(nurl)
        return self._send(200, {"status": "ok", "url": nurl})

    def _shutdown(self):
        self._send(200, {"status": "ok"})
        # 在独立线程里停止 serve_forever，确保本次响应能正常返回
        threading.Thread(
            target=lambda: (__import__("time").sleep(0.3), self.server.shutdown()),
            daemon=True).start()

    def _upload(self):
        body = self._body()
        name = SafeName(body.get("name", ""))
        if not name:
            return self._send(400, {"error": "缺少文件名"})
        slow = name.lower()
        if not slow.endswith((".pdf", ".docx", ".md", ".txt")):
            return self._send(400, {"error": "仅支持 PDF、Word、Markdown、纯文本"})
        core.ReloadTopicPaths()
        os.makedirs(core.rawsourcesdir, exist_ok=True)
        spath = os.path.join(core.rawsourcesdir, name)
        stmp = spath + ".part"
        try:
            bdata = base64.b64decode(body.get("data", ""))
        except Exception:
            return self._send(400, {"error": "上传数据编码损坏"})
        if len(bdata) > max_upload_bytes:
            return self._send(413, {"error": "文件过大（上限 %d MB）" % (max_upload_bytes // (1024 * 1024))})
        with open(stmp, "wb") as f:
            f.write(bdata)
        if os.path.getsize(stmp) <= 0:
            os.remove(stmp)
            return self._send(400, {"error": "文件为空或上传数据损坏"})
        os.replace(stmp, spath)
        sid = (body.get("id") or "").strip()
        if sid:
            core.BindRawfileToSource(sid, name)
        surl = wops.ResolveDoiUrl((body.get("url") or "").strip())
        if surl:
            core.SetPaperUrl(surl, srawfile=name)
        try:
            refresh.RefreshWiki(bwrite_files=True, bforce=True)
        except Exception as e:
            logger.warning("上传后刷新索引失败：%s", e)
        ometa = core.ParseSourceFilename(name)
        core.AppendLog("[upload] 添加文献 %s（key: %s）" % (name, ometa["key"]))
        return self._send(200, {
            "status": "ok", "name": name, "key": ometa["key"],
            "topic": topics.GetCurrentTopicId(),
            "total": len(core.ListSources()),
        })

    def _importbibtex(self):
        body = self._body()
        stext = (body.get("bibtex") or "").strip()
        if body.get("data"):
            try:
                stext = base64.b64decode(body.get("data", "")).decode("utf-8", errors="replace").strip()
            except Exception:
                return self._send(400, {"error": "BibTeX 数据编码损坏"})
        if not stext:
            return self._send(400, {"error": "缺少 BibTeX 内容"})
        core.ReloadTopicPaths()
        wops.Init(core.wikidir, core.rawsourcesdir, core.rootdir)
        oresult = bib_io.ImportBibtex(
            stext, core.wikidir, core.rawsourcesdir,
            bcreate_placeholder=body.get("create_placeholder", True),
        )
        refresh.InvalidateWikiCache()
        try:
            refresh.RefreshWiki(bwrite_files=True, bforce=True)
        except Exception as e:
            logger.warning("BibTeX 导入后刷新索引失败：%s", e)
        core.AppendLog("[bib] 导入 %d 条：更新 %d，新建 %d" % (
            oresult.get("total", 0),
            len(oresult.get("updated") or []),
            len(oresult.get("created") or []),
        ))
        return self._send(200, oresult)

    def _sourceurl(self):
        body = self._body()
        surl = wops.ResolveDoiUrl(body.get("url", ""))
        result = core.SetPaperUrl(
            surl,
            srawfile=body.get("rawfile") or None,
            skey=body.get("id") or None,
        )
        refresh.RefreshWiki(bwrite_files=True, bforce=True)
        core.AppendLog("[url] 更新文献链接 %s → %s" % (result.get("id") or result.get("rawfile"), result.get("url") or "（已清除）"))
        return self._send(200, result)

    def _sourcetags(self):
        body = self._body()
        sid = (body.get("id") or body.get("key") or "").strip()
        if not sid:
            return self._send(400, {"error": "缺少文献 id"})
        vtags = body.get("tags", [])
        if not isinstance(vtags, list):
            return self._send(400, {"error": "tags 须为数组"})
        try:
            vclean = core.SetLibTags(sid, vtags)
        except ValueError as e:
            return self._send(400, {"error": str(e)})
        core.AppendLog("[tags] 更新论文库标签 %s → %s" % (sid, ", ".join(vclean) or "（已清除）"))
        refresh.InvalidateWikiCache(core.wikidir)
        return self._send(200, {"id": sid, "tags": vclean})

    def _libraryassign(self):
        body = self._body()
        sid = (body.get("id") or body.get("key") or body.get("source_id") or "").strip()
        stype = (body.get("type") or body.get("group_type") or "").strip().lower()
        sgroup = (body.get("group") or body.get("group_id") or "").strip()
        saction = (body.get("action") or "add").strip().lower()
        if not sid:
            return self._send(400, {"error": "缺少文献 id"})
        try:
            oresult = core.AssignSourceGroup(sid, stype, sgroup, saction=saction)
        except ValueError as e:
            return self._send(400, {"error": str(e)})
        refresh.RefreshWiki(bwrite_files=True, bforce=True)
        core.AppendLog("[group] %s %s %s → %s" % (saction, stype, sid, sgroup or "（清除）"))
        return self._send(200, oresult)

    def _delete(self):
        body = self._body()
        sraw = SafeName(body.get("rawfile", ""))
        sid = (body.get("id") or body.get("key") or "").strip()
        if not sraw and not sid:
            return self._send(400, {"error": "缺少文献 id 或 rawfile"})
        wops.Init(core.wikidir, core.rawsourcesdir, core.rootdir)
        try:
            oresult = wops.DeleteSourceCascade(
                srawfile=sraw or None, skey=sid or None, bcascade=body.get("cascade", True))
        except ValueError as e:
            return self._send(400, {"error": str(e)})
        refresh.RefreshWiki(bwrite_files=True, bforce=True)
        core.AppendLog("[delete] 删除文献 %s（级联 %s，共 %d 项）" % (
            sid or sraw, "是" if body.get("cascade", True) else "否", len(oresult.get("removed", []))))
        return self._send(200, {"status": "ok", **oresult})

    def _ingestcancel(self):
        nuid = self._Uid()
        with ingestlock:
            ojob = GetIngestJob(nuid)
            if not ojob.get("running"):
                return self._send(200, {"status": "idle", **{k: v for k, v in ojob.items()
                                                             if k not in ("uid", "gen")}})
            ojob["cancelled"] = True
            return self._send(200, {k: v for k, v in dict(ojob, status="cancelling").items()
                                    if k not in ("uid", "gen")})

    def _query(self):
        body = self._body()
        squestion = (body.get("question") or "").strip()
        if not squestion:
            return self._send(400, {"error": "请输入问题"})
        oconfig = LoadConfig()
        noauth = "pollinations.ai" in (oconfig.get("base_url") or "")
        if not HasUsableApiKey(oconfig) and not noauth:
            return self._send(200, {"status": "need_key"})
        nuid = self._Uid()
        with querylock:
            ojob = GetQueryJob(nuid)
            if ojob.get("running"):
                if ojob.get("question") == squestion:
                    return self._send(200, dict(ojob, status="running"))
                return self._send(200, {
                    "status": "busy", "busy": "query",
                    "message": "上一条问答仍在进行，请稍后再提问。",
                })
        obusy = LlmBusyPayload(self._Uid())
        if obusy and obusy.get("busy") != "query":
            return self._send(200, self._MaybeOtherUserBusy(obusy))
        serr = self._CheckLlmQuota(1)
        if serr:
            return self._send(200, {"status": "error", "error": serr})
        bsave = body.get("save", True)
        ouser = getattr(self, "_user", None)
        sqid = uuid.uuid4().hex
        _, ngen = BeginQueryJob(
            nuid,
            running=True, question=squestion, answer="", error="",
            finished=False, saved=None, status="running", qid=sqid,
        )
        threading.Thread(
            target=RunQueryJob,
            args=(oconfig, squestion, bsave, ouser["root"] if ouser else None, nuid, ngen),
            daemon=True,
        ).start()
        return self._send(200, {"status": "started", "question": squestion, "qid": sqid})

    def _topicsnapshot(self):
        wops.Init(core.wikidir, core.rawsourcesdir, core.rootdir)
        oresult = wops.SnapshotTopic()
        core.AppendLog("[snapshot] 选题备份 %s" % oresult.get("path"))
        return self._send(200, oresult)

    def _docsimport(self):
        body = self._body()
        name = SafeName(body.get("name", ""))
        if not name.lower().endswith(".docx"):
            return self._send(400, {"error": "仅支持 docx"})
        sdata = body.get("data") or ""
        if not sdata:
            return self._send(400, {"error": "文件数据为空，请重新选择"})
        try:
            bcontent = base64.b64decode(sdata, validate=True)
        except Exception:
            return self._send(400, {"error": "文件编码损坏，请重新上传"})
        if len(bcontent) > max_upload_bytes:
            return self._send(413, {"error": "文件过大（上限 %d MB）" % (max_upload_bytes // (1024 * 1024))})
        core.ReloadTopicPaths()
        doced.Init(topics.GetTopicDir())
        try:
            result = doced.ImportDocx(
                bcontent,
                name,
                body.get("title"),
                body.get("tags"),
            )
        except ValueError as e:
            return self._send(400, {"error": str(e)})
        try:
            core.AppendLog("[doc] 导入文档 %s（%s）" % (result.get("title"), result.get("id")))
        except Exception:
            pass
        return self._send(200, result)

    def _docsmeta(self):
        body = self._body()
        doced.Init(topics.GetTopicDir())
        return self._send(200, doced.UpdateDocMeta(
            body.get("id", ""),
            body.get("title"),
            body.get("tags"),
        ))

    def _docsextract(self):
        body = self._body()
        doced.Init(topics.GetTopicDir())
        return self._send(200, doced.ExtractComments(body.get("id", "")))

    def _docstodo(self):
        body = self._body()
        doced.Init(topics.GetTopicDir())
        return self._send(200, doced.MarkTodoDone(
            body.get("id", ""),
            body.get("todo_id", ""),
            body.get("done", True),
        ))

    def _docsedit(self):
        body = self._body()
        doced.Init(topics.GetTopicDir())
        try:
            oresult = doced.ApplyEdit(
                body.get("id", ""),
                int(body.get("para_index", -1)),
                body.get("text", ""),
                body.get("comment_id"),
                body.get("html"),
                body.get("para_style"),
            )
        except ValueError as e:
            return self._send(400, {"error": str(e)})
        except Exception as e:
            logger.exception("文档段落保存失败")
            return self._send(500, {"error": str(e) if not multiuser else "保存失败，请稍后重试"})
        return self._send(200, oresult)

    def _docssave(self):
        body = self._body()
        doced.Init(topics.GetTopicDir())
        result = doced.SaveRevision(body.get("id", ""), body.get("message", ""))
        core.AppendLog("[doc] 保存版本 %s：%s" % (body.get("id"), result.get("message")))
        return self._send(200, result)

    def _docsrestore(self):
        body = self._body()
        doced.Init(topics.GetTopicDir())
        result = doced.RestoreRevision(body.get("id", ""), body.get("rev", ""))
        core.AppendLog("[doc] 恢复版本 %s → %s" % (body.get("id"), body.get("rev")))
        return self._send(200, result)

    def _docsrestoreworking(self):
        body = self._body()
        doced.Init(topics.GetTopicDir())
        result = doced.RestoreWorkingCopy(body.get("id", ""))
        core.AppendLog("[doc] 恢复文稿 %s" % body.get("id"))
        return self._send(200, result)

    def _docsdiscard(self):
        body = self._body()
        doced.Init(topics.GetTopicDir())
        result = doced.DiscardWorkingChanges(body.get("id", ""))
        core.AppendLog("[doc] 丢弃未保存的修改 %s" % body.get("id"))
        return self._send(200, result)

    def _docspickfolder(self):
        try:
            spath = PickFolderNative()
            if spath:
                _exportdir_cache[self._Uid()] = spath
            return self._send(200, {"path": spath or ""})
        except Exception as e:
            return self._send(500, {"error": str(e)})

    def _docsexport(self):
        body = self._body()
        doced.Init(topics.GetTopicDir())
        sdocid = (body.get("id") or "").strip()
        sfilename = body.get("filename", "")
        if not sdocid:
            return self._send(400, {"error": "缺少文档 id"})
        try:
            if multiuser:
                import urllib.parse
                bdata, sname = doced.ExportDocBytes(sdocid, sfilename)
                sexports = os.path.join(_boundroot, "exports")
                os.makedirs(sexports, exist_ok=True)
                spath = os.path.join(sexports, sname)
                with open(spath, "wb") as f:
                    f.write(bdata)
                result = {
                    "filename": sname,
                    "download": "/api/docs/download?id=%s&filename=%s" % (
                        urllib.parse.quote(sdocid, safe=""),
                        urllib.parse.quote(sname, safe=""),
                    ),
                }
            else:
                sdir = _exportdir_cache.get(self._Uid(), "")
                if not sdir:
                    return self._send(400, {"error": "请先通过「选择文件夹」指定导出目录"})
                result = doced.ExportDoc(sdocid, sdir, sfilename)
        except ValueError as e:
            return self._send(400, {"error": str(e)})
        except PermissionError:
            return self._send(403, {"error": "没有写入导出文件夹的权限，请换一个目录"})
        except OSError as e:
            return self._send(400, {"error": "无法写入导出路径：%s" % e})
        except Exception as e:
            logger.exception("文档导出失败 doc=%s", sdocid)
            return self._send(500, {"error": str(e) if not multiuser else "导出失败，请稍后重试"})
        try:
            core.AppendLog("[doc] 导出 %s → %s" % (sdocid, result.get("path") or result.get("filename")))
        except Exception:
            pass
        return self._send(200, result)

    def _docsdownload(self):
        import urllib.parse
        oq = urllib.parse.parse_qs(self.path.split("?", 1)[-1] if "?" in self.path else "")
        sid = (oq.get("id") or [""])[0]
        sfilename = (oq.get("filename") or ["export.docx"])[0]
        doced.Init(topics.GetTopicDir())
        try:
            bdata, sname = doced.ExportDocBytes(sid, sfilename)
        except ValueError as e:
            return self._send(400, {"error": str(e)})
        except Exception as e:
            logger.exception("文档下载失败 id=%s", sid)
            return self._send(500, {"error": str(e) if not multiuser else "下载失败，请稍后重试"})
        sencoded = urllib.parse.quote(sname)
        self.send_response(200)
        self.send_header(
            "Content-Type",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        self.send_header(
            "Content-Disposition",
            "attachment; filename=\"%s\"; filename*=UTF-8''%s" % (sname.replace('"', ""), sencoded),
        )
        self.send_header("Content-Length", str(len(bdata)))
        self.end_headers()
        self.wfile.write(bdata)

    def _docsdelete(self):
        body = self._body()
        doced.Init(topics.GetTopicDir())
        return self._send(200, doced.DeleteDoc(body.get("id", "")))

    def _ingest(self):
        body = self._body()
        oconfig = LoadConfig()
        nuid = self._Uid()
        with ingestlock:
            ojob = GetIngestJob(nuid)
            if ojob["running"]:
                return self._send(200, dict(ojob, status="running"))
        obusy = LlmBusyPayload(nuid)
        if obusy and obusy.get("busy") != "ingest":
            return self._send(200, self._MaybeOtherUserBusy(obusy))
        rawfile = body.get("rawfile")
        targets = [SafeName(rawfile)] if rawfile else core.PendingSources()
        if not targets:
            return self._send(200, {"status": "no_pending"})
        noauth = "pollinations.ai" in (oconfig.get("base_url") or "")
        if not HasUsableApiKey(oconfig) and not noauth:
            return self._send(200, {"status": "need_key", "pending": len(targets)})
        serr = self._CheckLlmQuota(len(targets))
        if serr:
            return self._send(200, {"status": "error", "error": serr})
        ouser = getattr(self, "_user", None)
        _, ngen = BeginIngestJob(
            nuid,
            running=True, total=len(targets), done=0, current="",
            ingested=[], failed=[], briefs=[], finished=False, cancelled=False,
        )
        threading.Thread(
            target=RunIngestJob,
            args=(oconfig, targets, ouser["root"] if ouser else None, nuid, ngen),
            daemon=True,
        ).start()
        return self._send(200, {"status": "started", "total": len(targets)})

    def _deep_analyze(self):
        """触发五阶段深度分析（须已纳入且保留原始 PDF）。"""
        oconfig = LoadConfig()
        body = self._body()
        sid = (body.get("id") or body.get("key") or "").strip()
        sfile = SafeName(body.get("rawfile") or "")
        if not sfile and sid:
            sfile = SafeName(core.ResolveRawfileForKey(sid))
        if sid and not core.FindSourcePagePath(sid):
            return self._send(400, {"error": "请先「纳入研究」后再进行深度分析"})
        if not sfile:
            return self._send(400, {"error": "找不到原始 PDF，深度研究需要 PDF 原文，请重新上传后再试"})
        spdf = os.path.join(core.rawsourcesdir, sfile)
        if not os.path.isfile(spdf):
            return self._send(400, {"error": "原始 PDF 不在文献库中，请重新上传后再进行深度分析"})
        noauth = "pollinations.ai" in (oconfig.get("base_url") or "")
        if not HasUsableApiKey(oconfig) and not noauth:
            return self._send(200, {"status": "need_key"})
        nuid = self._Uid()
        if rdeep.GetDeepJobStatus(nuid).get("running"):
            return self._send(200, {"error": "深度分析正在进行中，请等待完成"})
        obusy = LlmBusyPayload(nuid)
        if obusy and obusy.get("busy") != "deep":
            return self._send(200, self._MaybeOtherUserBusy(obusy))
        ouser = getattr(self, "_user", None)
        serr = self._CheckLlmQuota(5)
        if serr:
            return self._send(200, {"status": "error", "error": serr})
        oresult = rdeep.StartDeepAnalysis(
            oconfig, sfile, ouser["root"] if ouser else None, skey=sid or None, nuid=nuid)
        if "error" in oresult:
            return self._send(200, oresult)
        return self._send(200, {"status": "started", "file": sfile, "id": sid or ""})

    def _standard_analyze(self):
        """触发两阶段标准分析（须已纳入且保留原始 PDF）。"""
        oconfig = LoadConfig()
        body = self._body()
        sid = (body.get("id") or body.get("key") or "").strip()
        sfile = SafeName(body.get("rawfile") or "")
        if not sfile and sid:
            sfile = SafeName(core.ResolveRawfileForKey(sid))
        if sid and not core.FindSourcePagePath(sid):
            return self._send(400, {"error": "请先「纳入研究」后再进行标准分析"})
        if not sfile:
            return self._send(400, {"error": "找不到原始 PDF，标准分析需要 PDF 原文，请重新上传后再试"})
        spdf = os.path.join(core.rawsourcesdir, sfile)
        if not os.path.isfile(spdf):
            return self._send(400, {"error": "原始 PDF 不在文献库中，请重新上传后再进行标准分析"})
        noauth = "pollinations.ai" in (oconfig.get("base_url") or "")
        if not HasUsableApiKey(oconfig) and not noauth:
            return self._send(200, {"status": "need_key"})
        nuid = self._Uid()
        if rstd.GetStandardJobStatus(nuid).get("running"):
            return self._send(200, {"error": "标准分析正在进行中，请等待完成"})
        obusy = LlmBusyPayload(nuid)
        if obusy and obusy.get("busy") != "standard":
            return self._send(200, self._MaybeOtherUserBusy(obusy))
        ouser = getattr(self, "_user", None)
        serr = self._CheckLlmQuota(2)
        if serr:
            return self._send(200, {"status": "error", "error": serr})
        oresult = rstd.StartStandardAnalysis(
            oconfig, sfile, ouser["root"] if ouser else None, skey=sid or None, nuid=nuid)
        if "error" in oresult:
            return self._send(200, oresult)
        return self._send(200, {"status": "started", "file": sfile, "id": sid or ""})


def Main():
    url = "http://%s:%d" % (host, port)
    try:
        server = ThreadingHTTPServer((host, port), Handler)
    except OSError:
        # 端口被占用：通常是服务已在运行，直接打开网页即可
        print("检测到服务已在运行，正在打开网页：%s" % url)
        webbrowser.open(url)
        return
    refresh.RefreshWiki(bwrite_files=True)
    print("%s 已启动：%s" % (APP_NAME, url))
    print("（按 Ctrl+C 或关闭此窗口即停止）")
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
        server.shutdown()


if __name__ == "__main__":
    Main()
