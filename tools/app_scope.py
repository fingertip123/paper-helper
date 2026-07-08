#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""应用数据根绑定与请求级临界区（多用户隔离）。"""
import os
import threading
from contextlib import contextmanager

import wiki_core as core
import topic_manager as topics
import wiki_refresh as refresh
from app_meta import ResolveConfigDir

datalock = threading.RLock()
_boundroot = core.rootdir
bmultiuser = False
configdir = ResolveConfigDir(core.rootdir)
configpath = os.path.join(configdir, "config.json")


def InitScope(bmulti, nroot):
    """由 app.py 启动时调用，同步多用户标志与配置路径。"""
    global bmultiuser, configdir, configpath, _boundroot
    bmultiuser = bool(bmulti)
    _boundroot = nroot or core.rootdir
    configdir = ResolveConfigDir(_boundroot)
    configpath = os.path.join(configdir, "config.json")


@contextmanager
def UserScope(nroot=None):
    """请求 / 后台任务的文件操作临界区：持锁 + 绑定数据根。"""
    datalock.acquire()
    try:
        if bmultiuser and nroot:
            BindDataRoot(nroot)
        yield
    finally:
        datalock.release()


def BindDataRoot(nroot):
    """切换全局数据根（须在 datalock 内调用）。"""
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
