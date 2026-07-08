#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""文献库：上传、删除、标签、分组、文件服务。"""
import base64
import logging
import os

import app_context as actx
import bib_io
import topic_manager as topics
import wiki_core as core
import wiki_ops as wops
import wiki_refresh as refresh
from io_utils import SafeName

logger = logging.getLogger(__name__)


class HandlerLibraryMixin:

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
        if len(bdata) > actx.ctx.max_upload_bytes:
            return self._send(413, {"error": "文件过大（上限 %d MB）" % (actx.ctx.max_upload_bytes // (1024 * 1024))})
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
        if nsize > actx.ctx.pdf_max_serve_bytes:
            return self._send(413, {"error": "文件过大（上限 %d MB）" % (actx.ctx.pdf_max_serve_bytes // (1024 * 1024))})
        ctype = "application/pdf" if full.lower().endswith(".pdf") else "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(nsize))
        if full.lower().endswith(".pdf"):
            self.send_header("Content-Disposition", 'inline; filename="%s"' % os.path.basename(full))
        self.end_headers()
        with open(full, "rb") as f:
            while True:
                bchunk = f.read(actx.ctx.pdf_serve_chunk)
                if not bchunk:
                    break
                self.wfile.write(bchunk)
