#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WSGI 入口（PythonAnywhere 等仅支持 WSGI 的免费托管平台）。

PythonAnywhere 配置（Web → WSGI configuration file）填入：

    import sys
    sys.path.insert(0, "/home/<你的用户名>/paper-helper")
    from wsgi import application

数据默认存到 <项目根>/data（PythonAnywhere 磁盘持久，免费版约 512MB）。
"""
import io
import os
import sys
import site
from email.message import Message

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "tools"))


def _EnsureUserSite():
    """部分托管平台的 WSGI 进程未把 ~/.local 用户级包目录加入 sys.path，
    导致 pip install --user 装的依赖（如 python-docx）找不到。这里补回。"""
    vpaths = []
    try:
        spath = site.getusersitepackages()
        if isinstance(spath, str):
            vpaths.append(spath)
        else:
            vpaths.extend(spath)
    except Exception:
        pass
    nver = "python%d.%d" % (sys.version_info[0], sys.version_info[1])
    vpaths.append(os.path.join(os.path.expanduser("~"), ".local", "lib", nver, "site-packages"))
    for spath in vpaths:
        if spath and os.path.isdir(spath) and spath not in sys.path:
            sys.path.append(spath)


_EnsureUserSite()

import server as srv  # noqa: E402
import app as appmod  # noqa: E402

srv.Setup()


class _WsgiBridge(appmod.Handler):
    """把 WSGI environ 伪装成 BaseHTTPRequestHandler 的请求上下文。"""

    def __init__(self, environ):  # noqa: D107 — 故意不调用父类 __init__（无 socket）
        nlen = int(environ.get("CONTENT_LENGTH") or 0)
        self.rfile = io.BytesIO(environ["wsgi.input"].read(nlen) if nlen else b"")
        self.wfile = io.BytesIO()
        self.command = environ["REQUEST_METHOD"]
        squery = environ.get("QUERY_STRING", "")
        self.path = environ.get("PATH_INFO", "/") + (("?" + squery) if squery else "")
        self.request_version = "HTTP/1.1"
        self.protocol_version = "HTTP/1.1"
        self.requestline = "%s %s HTTP/1.1" % (self.command, self.path)
        self.client_address = (environ.get("REMOTE_ADDR", "0.0.0.0"), 0)
        self.headers = Message()
        if nlen:
            self.headers["Content-Length"] = str(nlen)
        if environ.get("HTTP_COOKIE"):
            self.headers["Cookie"] = environ["HTTP_COOKIE"]
        for skey, sval in environ.items():
            if skey.startswith("HTTP_") and skey not in ("HTTP_COOKIE",):
                self.headers[skey[5:].replace("_", "-").title()] = sval

    def Run(self):
        if self.command == "POST":
            self.do_POST()
        elif self.command == "GET":
            self.do_GET()
        else:
            self._send(405, {"error": "method not allowed"})
        return self.wfile.getvalue()


def application(environ, start_response):
    obridge = _WsgiBridge(environ)
    braw = obridge.Run()
    nsplit = braw.find(b"\r\n\r\n")
    bhead, bbody = braw[:nsplit], braw[nsplit + 4:]
    vlines = bhead.decode("iso-8859-1").split("\r\n")
    sstatus = vlines[0].split(" ", 1)[1]  # "200 OK"
    vheaders = []
    for sline in vlines[1:]:
        skey, _, sval = sline.partition(": ")
        if skey.lower() in ("server", "date"):
            continue
        vheaders.append((skey, sval))
    start_response(sstatus, vheaders)
    return [bbody]
