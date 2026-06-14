#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""应用品牌与路径常量（研栈）。"""
import os

APP_NAME = "研栈"
APP_SLUG = "Yanzhan"
BUNDLE_ID = "com.yanzhan.app"
CONFIG_DIRNAME = ".yanzhan"
CONFIG_DIRNAME_LEGACY = ".paper-helper"
DATA_DIRNAME = "Yanzhan"
DATA_DIRNAME_LEGACY = "PaperHelper"
GUI_ENV = "YANZHAN_GUI"


def ResolveConfigDir(nroot):
    """配置目录：优先 .yanzhan，兼容旧版 .paper-helper。"""
    for sname in (CONFIG_DIRNAME, CONFIG_DIRNAME_LEGACY):
        spath = os.path.join(nroot, sname)
        if os.path.isdir(spath):
            return spath
    return os.path.join(nroot, CONFIG_DIRNAME)


def ResolveDataDir():
    """打包版用户数据目录：优先 ~/Yanzhan，兼容 ~/PaperHelper。"""
    nhome = os.path.expanduser("~")
    nnew = os.path.join(nhome, DATA_DIRNAME)
    nlegacy = os.path.join(nhome, DATA_DIRNAME_LEGACY)
    if os.path.isdir(nnew):
        return nnew
    if os.path.isdir(nlegacy):
        return nlegacy
    return nnew


def LogDir():
    """日志目录。"""
    import sys
    if sys.platform == "darwin":
        return os.path.join(os.path.expanduser("~"), "Library", "Logs", APP_SLUG)
    if sys.platform.startswith("win"):
        return os.path.join(
            os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
            APP_SLUG, "logs",
        )
    return os.path.join(os.path.expanduser("~"), CONFIG_DIRNAME, "logs")
