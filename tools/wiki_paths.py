#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Wiki 数据根与选题路径管理。"""

import os
import sys
import shutil

rootdir = ""
wikidir = ""
rawsourcesdir = ""
outputpath = ""

def ResolveRootDir():
    """开发态返回项目根目录；打包态返回用户主目录下的可写数据目录。

    打包成 .app/.exe 后，程序自身位于只读 bundle 内，wiki/raw 等需读写的
    内容必须放到用户可写位置；首次运行从内置模板（seed）播种一份初始内容。
    """
    if not getattr(sys, "frozen", False):
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    from app_meta import ResolveDataDir
    ndatadir = ResolveDataDir()
    nseed = os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(sys.executable)), "seed")
    if not os.path.exists(ndatadir) and os.path.isdir(nseed):
        shutil.copytree(nseed, ndatadir)
    for nsub in ("", "wiki", "wiki/sources", "raw", "raw/sources", "raw/assets"):
        os.makedirs(os.path.join(ndatadir, nsub), exist_ok=True)
    return ndatadir


rootdir = ResolveRootDir()

import topic_manager as topics  # noqa: E402
import wiki_ops as wops  # noqa: E402
import doc_editor as docs  # noqa: E402

topics.Init(rootdir)


def ReloadTopicPaths():
    """切换选题后刷新 wiki/raw 路径。"""
    global wikidir, rawsourcesdir
    nactive = topics.GetTopicDir()
    wikidir = os.path.join(nactive, "wiki")
    rawsourcesdir = os.path.join(nactive, "raw", "sources")
    os.makedirs(wikidir, exist_ok=True)
    os.makedirs(rawsourcesdir, exist_ok=True)
    wops.Init(wikidir, rawsourcesdir, rootdir)
    docs.Init(topics.GetTopicDir())


ReloadTopicPaths()
outputpath = os.path.join(rootdir, "wiki-viewer.html")


def SetDataRoot(nroot):
    """多用户后台任务切换数据根（与 app.BindDataRoot 的路径逻辑一致）。"""
    if not nroot:
        return
    global rootdir
    rootdir = nroot
    topics.Init(nroot)
    ReloadTopicPaths()
