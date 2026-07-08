#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""文档编辑器 API。"""
import base64
import logging
import os
import sys

import app_context as actx
import app_scope
import doc_editor as doced
import topic_manager as topics
import wiki_core as core
from app_native import PickFolderNative, exportdir_cache
from io_utils import SafeName

logger = logging.getLogger(__name__)


class HandlerDocsMixin:

    def _GetDocsList(self):
        doced.Init(topics.GetTopicDir())
        import urllib.parse
        oq = urllib.parse.parse_qs(self.path.split("?", 1)[-1] if "?" in self.path else "")
        return self._send(200, doced.ListDocs((oq.get("tag") or [None])[0]))


    def _GetDocsDetail(self):
        import urllib.parse
        oq = urllib.parse.parse_qs(self.path.split("?", 1)[-1] if "?" in self.path else "")
        sid = (oq.get("id") or [""])[0]
        blight = (oq.get("light") or ["0"])[0] in ("1", "true", "yes")
        doced.Init(topics.GetTopicDir())
        try:
            return self._send(200, doced.GetDocDetail(sid, blight))
        except ValueError as e:
            return self._send(400, {"error": str(e)})


    def _GetDocsPreview(self):
        import urllib.parse
        oq = urllib.parse.parse_qs(self.path.split("?", 1)[-1] if "?" in self.path else "")
        sid = (oq.get("id") or [""])[0]
        doced.Init(topics.GetTopicDir())
        return self._send(200, doced.GetPreviewHtml(sid), "text/html; charset=utf-8")


    def _GetDocsRevisions(self):
        import urllib.parse
        oq = urllib.parse.parse_qs(self.path.split("?", 1)[-1] if "?" in self.path else "")
        sid = (oq.get("id") or [""])[0]
        doced.Init(topics.GetTopicDir())
        return self._send(200, doced.ListRevisions(sid))


    def _GetDocsRevision(self):
        import urllib.parse
        oq = urllib.parse.parse_qs(self.path.split("?", 1)[-1] if "?" in self.path else "")
        sid = (oq.get("id") or [""])[0]
        srev = (oq.get("rev") or [""])[0]
        doced.Init(topics.GetTopicDir())
        return self._send(200, doced.GetRevisionDetail(sid, srev))


    def _GetDocsStatus(self):
        import urllib.parse
        oq = urllib.parse.parse_qs(self.path.split("?", 1)[-1] if "?" in self.path else "")
        sid = (oq.get("id") or [""])[0]
        doced.Init(topics.GetTopicDir())
        return self._send(200, doced.GetWorkingStatus(sid))


    def _GetDocsCompare(self):
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
        if len(bcontent) > actx.ctx.max_upload_bytes:
            return self._send(413, {"error": "文件过大（上限 %d MB）" % (actx.ctx.max_upload_bytes // (1024 * 1024))})
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
            return self._send(500, {"error": str(e) if not actx.ctx.multiuser else "保存失败，请稍后重试"})
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
                exportdir_cache[self._Uid()] = spath
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
            if actx.ctx.multiuser:
                import urllib.parse
                bdata, sname = doced.ExportDocBytes(sdocid, sfilename)
                sexports = os.path.join(app_scope._boundroot, "exports")
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
                sdir = exportdir_cache.get(self._Uid(), "")
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
            return self._send(500, {"error": str(e) if not actx.ctx.multiuser else "导出失败，请稍后重试"})
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
            return self._send(500, {"error": str(e) if not actx.ctx.multiuser else "下载失败，请稍后重试"})
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
