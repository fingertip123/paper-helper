#!/usr/bin/env python3
"""博士论文 Wiki 本地服务：在网页里完成 添加 / 分析 / 删除 / 刷新。

启动：
    python3 tools/app.py
然后浏览器访问 http://127.0.0.1:8765 （启动器会自动打开）。

「分析」需在网页「设置」里填写大模型 API（OpenAI 兼容）。未填写时返回 need_key，
网页会提示并打开设置；此即"排队回退"——你也可改在 Cursor 里让 AI 摄入。
"""

import os
import re
import json
import base64
import threading
import webbrowser
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import wiki_core as core
import topic_manager as topics
import wiki_ops as wops

host = "127.0.0.1"
port = 8765
desktopmode = False  # desktop.py 启动时设为 True，界面走桌面模式（服务开关控制功能而非关进程）
configdir = os.path.join(core.rootdir, ".paper-helper")
configpath = os.path.join(configdir, "config.json")

# 摄入任务进度（供前端轮询；同一时刻只跑一个任务）
ingestlock = threading.Lock()
ingestjob = {"running": False, "total": 0, "done": 0, "current": "",
             "ingested": [], "failed": [], "finished": False, "cancelled": False}


def LoadConfig():
    if os.path.isfile(configpath):
        try:
            with open(configpath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"base_url": "https://api.openai.com/v1", "api_key": "", "model": "gpt-4o-mini", "language": "中文"}


def SaveConfig(oconfig):
    os.makedirs(configdir, exist_ok=True)
    merged = LoadConfig()
    merged.update({k: v for k, v in oconfig.items() if k in ("base_url", "api_key", "model", "language")})
    with open(configpath, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)
    return merged


def SafeName(nfilename):
    """只保留文件名本身，去掉路径分隔符，防止目录穿越。"""
    return os.path.basename(nfilename).replace("\x00", "")


def SafeWikiPath(nrelpath):
    """校验 LLM 返回的写入路径必须落在 wiki/ 目录内且为 .md 文件。"""
    nrelpath = nrelpath.replace("\\", "/").lstrip("/")
    if not nrelpath.startswith("wiki/") or not nrelpath.endswith(".md") or ".." in nrelpath:
        return None
    fullpath = os.path.normpath(os.path.join(core.rootdir, nrelpath))
    if not fullpath.startswith(core.wikidir):
        return None
    return fullpath


def ExtractPaperText(nfullpath):
    """提取 PDF / docx / 文本 内容。"""
    slow = nfullpath.lower()
    if slow.endswith((".md", ".txt")):
        with open(nfullpath, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    if slow.endswith(".docx"):
        from docx import Document
        odoc = Document(nfullpath)
        return "\n".join(p.text for p in odoc.paragraphs if p.text.strip())
    from pdfminer.high_level import extract_text
    return extract_text(nfullpath) or ""


def CallLlm(oconfig, vmessages, bjson=True):
    """调用 OpenAI 兼容的 chat/completions 接口，返回助手文本。"""
    url = oconfig["base_url"].rstrip("/") + "/chat/completions"
    nbaseurl = oconfig.get("base_url") or ""
    payload = {
        "model": oconfig.get("model") or "gpt-4o-mini",
        "messages": vmessages,
        "temperature": 0.2,
    }
    if bjson and "pollinations.ai" not in nbaseurl:
        payload["response_format"] = {"type": "json_object"}
    data = json.dumps(payload).encode("utf-8")
    oheaders = {"Content-Type": "application/json"}
    if oconfig.get("api_key"):  # 免注册端点可无 Key，无 Key 时不发 Authorization
        oheaders["Authorization"] = "Bearer " + oconfig["api_key"]
    req = urllib.request.Request(url, data=data, method="POST", headers=oheaders)
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            obj = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        ndetail = e.read().decode("utf-8", "ignore")[:300]
        raise RuntimeError("接口返回 %s：%s" % (e.code, ndetail))
    if not obj.get("choices"):  # 免注册端点限流/异常时常返回无 choices 的对象
        raise RuntimeError("接口未返回有效结果：" + json.dumps(obj, ensure_ascii=False)[:300])
    return obj["choices"][0]["message"]["content"]


def ParseLlmJson(ntext):
    """容错解析 LLM 输出的 JSON（去掉可能的代码围栏）。"""
    s = ntext.strip()
    s = re.sub(r"^```(json)?\s*|\s*```$", "", s, flags=re.IGNORECASE)
    start, end = s.find("{"), s.rfind("}")
    if start >= 0 and end > start:
        s = s[start:end + 1]
    return json.loads(s)


def BuildIngestMessages(oconfig, nfilename, npapertext):
    """构造两步摄入的提示词：分析 + 生成 wiki 页面（JSON 输出）。"""
    with open(topics.RulePath("purpose.md"), "r", encoding="utf-8") as f:
        purpose = f.read()[:2500]
    vnodes, _ = core.ScanWiki()
    existing = "\n".join("- %s (%s): %s" % (n["id"], n["type"], n.get("title", "")) for n in vnodes)[:3000]
    meta = core.ParseSourceFilename(nfilename)
    lang = oconfig.get("language", "中文")
    system = (
        "你是个人学术知识库（LLM Wiki 范式）的摄入引擎。把一篇文献编译成相互链接的 Markdown wiki 页面。"
        "严格遵守：(1) 每个页面以 YAML frontmatter 开头，含 type/title/aliases/sources/tags/created/updated；"
        "source 页另含 url（论文在线阅读链接，优先 DOI https://doi.org/... 或期刊/出版社官网，无法确定则省略）；"
        "(2) 用 [[wikilink]] 做交叉引用，尽量复用已存在的页面 id；"
        "(3) 文件命名 kebab-case；(4) 只输出 JSON，不要多余文字。"
        "页面类型与目录：source→wiki/sources、concept→wiki/concepts、entity→wiki/entities、"
        "rq→wiki/research-questions、experiment→wiki/experiments、synthesis→wiki/synthesis、"
        "comparison→wiki/comparisons、query→wiki/queries。"
        "用%s撰写正文。" % lang
    )
    user = (
        "## 论文目标(purpose.md 摘录)\n%s\n\n"
        "## 已存在的 wiki 页面(可复用其 id 做链接)\n%s\n\n"
        "## 待摄入文献\n文件名：%s\n建议引用key：%s\n正文(截断)：\n%s\n\n"
        "## 输出 JSON 格式\n"
        '{\n'
        '  "key": "作者姓-年份",\n'
        '  "files": [\n'
        '    {"path": "wiki/sources/<key>.md", "content": "---\\ntype: source\\n...---\\n正文..."},\n'
        '    {"path": "wiki/concepts/<id>.md", "content": "..."}\n'
        '  ],\n'
        '  "log": "一句话操作摘要",\n'
        '  "review": ["需要人工核实的点"]\n'
        '}\n'
        "要求：必须包含 1 个 source 摘要页；为关键概念/方法/实体/作者各建页面（3-8 个）并相互 [[链接]]；"
        "source 页 frontmatter 的 sources 写 [%s]；尽量填写 url 字段。" % (purpose, existing, nfilename, meta["key"], npapertext[:14000], meta["key"])
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def IngestOne(oconfig, nfilename):
    """摄入单篇文献：提取文本→LLM→写入 wiki 页面。返回写入的相对路径列表。"""
    fullpath = os.path.join(core.rawsourcesdir, SafeName(nfilename))
    if not os.path.isfile(fullpath):
        raise FileNotFoundError(nfilename)
    text = ExtractPaperText(fullpath)
    if not text.strip():
        raise ValueError("无法提取文本（可能是扫描版 PDF）")
    content = CallLlm(oconfig, BuildIngestMessages(oconfig, nfilename, text))
    result = ParseLlmJson(content)
    vwritten = []
    for item in result.get("files", []):
        fp = SafeWikiPath(item.get("path", ""))
        body = item.get("content", "")
        if not fp or not body.strip():
            continue
        os.makedirs(os.path.dirname(fp), exist_ok=True)
        with open(fp, "w", encoding="utf-8") as f:
            f.write(body)
        vwritten.append(os.path.relpath(fp, core.rootdir))
    if not vwritten:
        raise ValueError("LLM 未返回有效页面")
    skey = result.get("key") or core.ParseSourceFilename(nfilename)["key"]
    core.MergePendingUrlToSource(nfilename, skey)
    logmsg = result.get("log") or ("摄入 %s" % nfilename)
    review = result.get("review") or []
    core.AppendLog("[ingest] %s（新增 %d 页）%s" % (
        logmsg, len(vwritten), ("；待核实：" + "；".join(review)) if review else ""))
    return vwritten


def RunIngestJob(oconfig, vtargets):
    """后台线程：逐篇摄入并实时更新 ingestjob 进度。"""
    global ingestjob
    for fn in vtargets:
        with ingestlock:
            if ingestjob.get("cancelled"):
                break
            ingestjob["current"] = fn
        try:
            IngestOne(oconfig, fn)
            with ingestlock:
                ingestjob["ingested"].append(fn)
        except Exception as e:
            with ingestlock:
                ingestjob["failed"].append({"file": fn, "error": str(e)})
        with ingestlock:
            ingestjob["done"] += 1
    core.GenerateIndex()
    with ingestlock:
        ingestjob["running"] = False
        ingestjob["finished"] = True
        ingestjob["current"] = ""
        if ingestjob.get("cancelled"):
            ingestjob["failed"].append({"file": "(已取消)", "error": "用户取消剩余任务"})


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length).decode("utf-8")) if length else {}

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            core.GenerateIndex()
            return self._send(200, core.Render(core.BuildData(), servermode=True, desktopmode=desktopmode), "text/html; charset=utf-8")
        if path == "/api/data":
            core.GenerateIndex()
            return self._send(200, core.BuildData())
        if path == "/api/config":
            c = dict(LoadConfig())
            c["api_key"] = "***" if c.get("api_key") else ""  # 不回传明文
            return self._send(200, c)
        if path == "/api/ingest/progress":
            with ingestlock:
                return self._send(200, dict(ingestjob))
        if path == "/api/lint":
            wops.Init(core.wikidir, core.rawsourcesdir, core.rootdir)
            return self._send(200, wops.RunLint())
        if path == "/api/export/bibtex":
            wops.Init(core.wikidir, core.rawsourcesdir, core.rootdir)
            return self._send(200, {"bibtex": wops.ExportBibtex()})
        if path == "/api/topics":
            return self._send(200, {
                "topics": topics.ListTopics(),
                "current": topics.GetCurrentTopicId(),
                "purpose_fields": topics.GetPurposeFieldDefs(),
            })
        if path == "/api/rules":
            return self._send(200, topics.GetRules())
        if path == "/api/topics/config":
            import urllib.parse
            oquery = urllib.parse.parse_qs(self.path.split("?", 1)[-1] if "?" in self.path else "")
            nid = (oquery.get("id") or [""])[0]
            return self._send(200, topics.GetTopicConfig(nid))
        if path.startswith("/raw/sources/"):
            return self._serve_file(path)
        return self._send(404, {"error": "not found"})

    def _serve_file(self, path):
        import urllib.parse
        rel = urllib.parse.unquote(path.lstrip("/"))
        if not rel.startswith("raw/sources/"):
            return self._send(404, {"error": "file not found"})
        nfilename = rel.split("raw/sources/", 1)[1]
        full = os.path.normpath(os.path.join(core.rawsourcesdir, nfilename))
        if not full.startswith(os.path.normpath(core.rawsourcesdir)) or not os.path.isfile(full):
            return self._send(404, {"error": "file not found"})
        ctype = "application/pdf" if full.lower().endswith(".pdf") else "application/octet-stream"
        with open(full, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        if full.lower().endswith(".pdf"):
            self.send_header("Content-Disposition", 'inline; filename="%s"' % os.path.basename(full))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        try:
            if self.path == "/api/upload":
                return self._upload()
            if self.path == "/api/delete":
                return self._delete()
            if self.path == "/api/ingest":
                return self._ingest()
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
            if self.path == "/api/ingest/cancel":
                return self._ingestcancel()
            if self.path == "/api/query":
                return self._query()
            if self.path == "/api/topics/snapshot":
                return self._topicsnapshot()
            return self._send(404, {"error": "not found"})
        except Exception as e:
            return self._send(500, {"error": str(e)})

    def _topicswitch(self):
        body = self._body()
        result = topics.SwitchTopic(body.get("id", ""))
        core.ReloadTopicPaths()
        core.GenerateIndex()
        return self._send(200, result)

    def _topicnew(self):
        body = self._body()
        result = topics.CreateTopic(
            body.get("name", "新选题"),
            body.get("fields"),
            True,
            body.get("import_from"),
        )
        core.ReloadTopicPaths()
        core.GenerateIndex()
        core.AppendLog("新建选题：%s（%s）" % (result.get("name"), result.get("id")))
        return self._send(200, result)

    def _topicreset(self):
        result = topics.ResetCurrentTopic()
        core.ReloadTopicPaths()
        core.GenerateIndex()
        core.AppendLog("重置选题：%s" % result.get("name"))
        return self._send(200, result)

    def _rulessave(self):
        body = self._body()
        skey = body.get("key", "")
        topics.SaveRule(skey, content=body.get("content"), ofields=body.get("fields"))
        return self._send(200, {"status": "ok"})

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
        os.makedirs(core.rawsourcesdir, exist_ok=True)
        with open(os.path.join(core.rawsourcesdir, name), "wb") as f:
            f.write(base64.b64decode(body.get("data", "")))
        surl = wops.ResolveDoiUrl((body.get("url") or "").strip())
        if surl:
            core.SetPaperUrl(surl, srawfile=name)
        return self._send(200, {"status": "ok", "name": name})

    def _sourceurl(self):
        body = self._body()
        surl = wops.ResolveDoiUrl(body.get("url", ""))
        result = core.SetPaperUrl(
            surl,
            srawfile=body.get("rawfile") or None,
            skey=body.get("id") or None,
        )
        core.GenerateIndex()
        core.AppendLog("[url] 更新文献链接 %s → %s" % (result.get("id") or result.get("rawfile"), result.get("url") or "（已清除）"))
        return self._send(200, result)

    def _delete(self):
        body = self._body()
        name = SafeName(body.get("rawfile", ""))
        wops.Init(core.wikidir, core.rawsourcesdir, core.rootdir)
        oresult = wops.DeleteSourceCascade(name, body.get("cascade", True))
        core.GenerateIndex()
        core.AppendLog("[delete] 删除文献 %s（级联 %s，共 %d 项）" % (
            name, "是" if body.get("cascade", True) else "否", len(oresult.get("removed", []))))
        return self._send(200, {"status": "ok", **oresult})

    def _ingestcancel(self):
        global ingestjob
        with ingestlock:
            ingestjob["cancelled"] = True
        return self._send(200, {"status": "cancelling"})

    def _query(self):
        body = self._body()
        squestion = (body.get("question") or "").strip()
        if not squestion:
            return self._send(400, {"error": "请输入问题"})
        oconfig = LoadConfig()
        noauth = "pollinations.ai" in (oconfig.get("base_url") or "")
        if not oconfig.get("api_key") and not noauth:
            return self._send(200, {"status": "need_key"})
        wops.Init(core.wikidir, core.rawsourcesdir, core.rootdir)
        scontext = wops.CollectQueryContext(squestion)
        slang = oconfig.get("language", "中文")
        vmessages = [
            {"role": "system", "content": (
                "你是博士论文知识库助手。仅根据提供的 wiki 页面作答，引用页面 id 如 [[kaplaner-2025]]。"
                "不确定处标明待核实。用%s回答。" % slang
            )},
            {"role": "user", "content": "知识库摘录：\n%s\n\n问题：%s" % (scontext, squestion)},
        ]
        sanswer = CallLlm(oconfig, vmessages, bjson=False)
        osaved = None
        if body.get("save", True):
            osaved = wops.SaveQueryPage(squestion, sanswer)
            core.GenerateIndex()
            core.AppendLog("[query] %s → %s" % (squestion[:60], osaved.get("id")))
        return self._send(200, {"answer": sanswer, "saved": osaved})

    def _topicsnapshot(self):
        wops.Init(core.wikidir, core.rawsourcesdir, core.rootdir)
        oresult = wops.SnapshotTopic()
        core.AppendLog("[snapshot] 选题备份 %s" % oresult.get("path"))
        return self._send(200, oresult)

    def _ingest(self):
        global ingestjob
        body = self._body()
        oconfig = LoadConfig()
        with ingestlock:
            if ingestjob["running"]:  # 已有任务在跑：返回当前进度，前端继续轮询
                return self._send(200, dict(ingestjob, status="running"))
        rawfile = body.get("rawfile")
        targets = [SafeName(rawfile)] if rawfile else core.PendingSources()
        if not targets:
            return self._send(200, {"status": "no_pending"})
        noauth = "pollinations.ai" in (oconfig.get("base_url") or "")  # 免注册端点跳过 Key 检查
        if not oconfig.get("api_key") and not noauth:
            return self._send(200, {"status": "need_key", "pending": len(targets)})
        with ingestlock:
            ingestjob = {"running": True, "total": len(targets), "done": 0, "current": "",
                         "ingested": [], "failed": [], "finished": False, "cancelled": False}
        threading.Thread(target=RunIngestJob, args=(oconfig, targets), daemon=True).start()
        return self._send(200, {"status": "started", "total": len(targets)})


def Main():
    url = "http://%s:%d" % (host, port)
    try:
        server = ThreadingHTTPServer((host, port), Handler)
    except OSError:
        # 端口被占用：通常是服务已在运行，直接打开网页即可
        print("检测到服务已在运行，正在打开网页：%s" % url)
        webbrowser.open(url)
        return
    core.GenerateIndex()
    print("博士论文 Wiki 已启动：%s" % url)
    print("（按 Ctrl+C 或关闭此窗口即停止）")
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
        server.shutdown()


if __name__ == "__main__":
    Main()
