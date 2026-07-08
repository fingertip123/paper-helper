#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""应用数据根绑定与请求级临界区（多用户隔离）。"""
import os
import threading
from contextlib import contextmanager

import wiki_core as core
import data_context as dctx
from app_meta import ResolveConfigDir

datalock = threading.RLock()
_boundroot = core.rootdir
bmultiuser = False
_dataprefix = ""  # 多用户数据根：所有用户目录必须落在其下
configdir = ResolveConfigDir(core.rootdir)
configpath = os.path.join(configdir, "config.json")


def InitScope(bmulti, nroot):
    """由 app.py 启动时调用，同步多用户标志与配置路径。"""
    global bmultiuser, configdir, configpath, _boundroot, _dataprefix
    bmultiuser = bool(bmulti)
    _boundroot = nroot or core.rootdir
    _dataprefix = os.path.normpath(os.path.abspath(_boundroot)) if bmultiuser else ""
    configdir = ResolveConfigDir(_boundroot)
    configpath = os.path.join(configdir, "config.json")


def _AssertWithinDataRoot(nroot):
    """多用户隔离护栏：用户数据根必须落在配置的数据目录内，否则拒绝绑定。"""
    if not _dataprefix:
        return
    nfull = os.path.normpath(os.path.abspath(nroot))
    if not (nfull == _dataprefix or nfull.startswith(_dataprefix + os.sep)):
        raise ValueError("非法数据根：%s 不在多用户数据目录内" % nroot)


@contextmanager
def UserScope(nroot=None):
    """请求 / 后台任务的文件操作临界区：持锁 + 绑定数据根。"""
    datalock.acquire()
    try:
        if bmultiuser and nroot:
            _AssertWithinDataRoot(nroot)
            BindDataRoot(nroot)
        yield
    finally:
        datalock.release()


def BindDataRoot(nroot):
    """切换全局数据根（须在 datalock 内调用）。"""
    global configdir, configpath, _boundroot
    if not nroot or nroot == _boundroot:
        return
    dctx.DataContext(nroot)
    _boundroot = nroot
    configdir = ResolveConfigDir(nroot)
    configpath = os.path.join(configdir, "config.json")
