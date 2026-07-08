#!/usr/bin/env python3
"""研栈本地服务：在网页里完成 添加 / 分析 / 删除 / 刷新。

启动：
    python3 tools/app.py
然后浏览器访问 http://127.0.0.1:8765 （启动器会自动打开）。

新用户默认使用内置智谱 GLM-4-Flash；也可在「偏好设置」中替换为自己的 API。
未配置且无内置 Key 时返回 need_key，网页会提示并打开设置。
"""

import logging
import sys
import threading
import types
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

logger = logging.getLogger(__name__)

import wiki_core as core
import wiki_refresh as refresh
import app_scope
import app_context as actx
from app_meta import APP_NAME
from handlers_auth import HandlerAuthMixin
from handlers_base import HandlerBaseMixin
from handlers_desktop import HandlerDesktopMixin
from handlers_docs import HandlerDocsMixin
from handlers_ingest import HandlerIngestMixin
from handlers_library import HandlerLibraryMixin
from handlers_query import HandlerQueryMixin
from handlers_topics import HandlerTopicsMixin
from handlers_wiki import HandlerWikiMixin

actx.Init(core.rootdir, False)
actx.ctx.baseroot = core.rootdir
app_scope.InitScope(actx.ctx.multiuser, core.rootdir)
UserScope = app_scope.UserScope

_CTX_FIELDS = frozenset({
    "host", "port", "desktopmode", "desktop_pick_folder", "multiuser", "llmdailylimit",
    "baseroot", "pdf_max_serve_bytes", "pdf_serve_chunk", "max_body_bytes", "max_upload_bytes",
})


def SyncCtxGlobals():
    """将 AppContext 字段同步到模块 globals，供 app.py 内 LOAD_GLOBAL 解析。"""
    omod = sys.modules[__name__]
    for sname in _CTX_FIELDS:
        dict.__setitem__(omod.__dict__, sname, getattr(actx.ctx, sname))


SyncCtxGlobals()


class _AppModule(types.ModuleType):
    """把 app.* 上下文字段的读写代理到 AppContext（actx.ctx）。

    注意：Python 模块并不支持模块级 `__setattr__` 钩子（PEP 562 只提供 `__getattr__`），
    因此必须替换模块对象的类，`appmod.multiuser = X` 之类的赋值才会真正同步到 actx.ctx，
    否则处理器读取的 actx.ctx.multiuser 会一直是默认值 False（登录网关与多用户隔离失效）。
    """

    def __getattr__(self, name):
        if name in _CTX_FIELDS:
            return getattr(actx.ctx, name)
        raise AttributeError("module %r has no attribute %r" % (__name__, name))

    def __setattr__(self, name, value):
        if name in _CTX_FIELDS:
            setattr(actx.ctx, name, value)
            self.__dict__[name] = value
            if name == "multiuser":
                app_scope.InitScope(bool(value), actx.ctx.baseroot or core.rootdir)
            return
        self.__dict__[name] = value


sys.modules[__name__].__class__ = _AppModule


class Handler(
    HandlerBaseMixin,
    HandlerAuthMixin,
    HandlerWikiMixin,
    HandlerTopicsMixin,
    HandlerLibraryMixin,
    HandlerIngestMixin,
    HandlerQueryMixin,
    HandlerDocsMixin,
    HandlerDesktopMixin,
    BaseHTTPRequestHandler,
):
    _last_code = 200
    _req_method = ""
    _req_path = ""


def Main():
    host, port = actx.ctx.host, actx.ctx.port
    url = "http://%s:%d" % (host, port)
    try:
        server = ThreadingHTTPServer((host, port), Handler)
    except OSError:
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
