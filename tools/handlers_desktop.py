#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""桌面端系统操作。"""
import os
import threading
import webbrowser

import app_context as actx
import wiki_core as core
from io_utils import SafeName


class HandlerDesktopMixin:

    def _openpdf(self):
        """桌面端 QWebEngine 内嵌 iframe 无法正常预览 PDF，改由系统浏览器打开。"""
        import urllib.parse
        body = self._body()
        nfilename = SafeName(body.get("rawfile", ""))
        if not nfilename:
            return self._send(400, {"error": "缺少文件名"})
        nbase = os.path.normpath(core.rawsourcesdir)
        nfull = os.path.normpath(os.path.join(core.rawsourcesdir, nfilename))
        if not (nfull == nbase or nfull.startswith(nbase + os.sep)) or not os.path.isfile(nfull):
            return self._send(404, {"error": "PDF 不存在"})
        nurl = "http://%s:%d/raw/sources/%s" % (
            actx.ctx.host, actx.ctx.port, urllib.parse.quote(nfilename))
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
