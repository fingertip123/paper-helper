#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""原子文件写入与路径安全工具（无项目内依赖，可被任意模块导入）。"""
import json
import os
import tempfile


def SafeName(nfilename):
    """只保留文件名本身，去掉路径分隔符，防止目录穿越。"""
    return os.path.basename(nfilename or "").replace("\x00", "")


def AtomicWriteText(spath, stext, encoding="utf-8"):
    """写临时文件后 rename，避免进程崩溃导致目标文件截断损坏。"""
    sdir = os.path.dirname(os.path.abspath(spath)) or "."
    os.makedirs(sdir, exist_ok=True)
    nfd, stmp = tempfile.mkstemp(dir=sdir, suffix=".tmp", prefix=".atomic-")
    try:
        with os.fdopen(nfd, "w", encoding=encoding) as f:
            f.write(stext)
        os.replace(stmp, spath)
    except Exception:
        try:
            os.remove(stmp)
        except OSError:
            pass
        raise


def AtomicWriteJson(spath, odata):
    AtomicWriteText(spath, json.dumps(odata, ensure_ascii=False, indent=2))


def AtomicWriteBytes(spath, bdata):
    sdir = os.path.dirname(os.path.abspath(spath)) or "."
    os.makedirs(sdir, exist_ok=True)
    nfd, stmp = tempfile.mkstemp(dir=sdir, suffix=".tmp", prefix=".atomic-")
    try:
        with os.fdopen(nfd, "wb") as f:
            f.write(bdata)
        os.replace(stmp, spath)
    except Exception:
        try:
            os.remove(stmp)
        except OSError:
            pass
        raise
