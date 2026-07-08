#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""文档编辑器路径与清单 I/O（doc_editor 拆分底层）。"""
import os
import re
import json
from datetime import datetime

_docsdir = ""
_docidre = re.compile(r"^[\w\u4e00-\u9fff-]{1,64}$")


def Init(ntopicdir):
    global _docsdir
    _docsdir = os.path.join(ntopicdir, "docs")
    os.makedirs(_docsdir, exist_ok=True)


def DocsDir():
    return _docsdir


def ManifestPath():
    return os.path.join(_docsdir, "index.json")


def ValidateDocId(sdocid):
    sid = (sdocid or "").strip()
    if not sid or not _docidre.match(sid):
        raise ValueError("无效的文档 id")
    return sid


def DocDir(sdocid):
    sid = ValidateDocId(sdocid)
    spath = os.path.join(_docsdir, sid)
    nbase = os.path.normpath(os.path.abspath(_docsdir))
    nfull = os.path.normpath(os.path.abspath(spath))
    if not (nfull == nbase or nfull.startswith(nbase + os.sep)):
        raise ValueError("无效的文档 id")
    return spath


def ReadJson(spath, sdefault=None):
    if not os.path.isfile(spath):
        return sdefault if sdefault is not None else {}
    with open(spath, "r", encoding="utf-8") as f:
        return json.load(f)


def WriteJson(spath, odata):
    os.makedirs(os.path.dirname(spath), exist_ok=True)
    with open(spath, "w", encoding="utf-8") as f:
        json.dump(odata, f, ensure_ascii=False, indent=2)


def ReadManifest():
    omanifest = ReadJson(ManifestPath(), {"docs": []})
    if "docs" not in omanifest:
        omanifest["docs"] = []
    return omanifest


def WriteManifest(omanifest):
    WriteJson(ManifestPath(), omanifest)


def NewDocId(sfilename):
    sbase = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", os.path.splitext(sfilename)[0]).strip("-").lower()
    if not sbase:
        sbase = "doc"
    sdocid = sbase[:40]
    if os.path.isdir(DocDir(sdocid)):
        sdocid = "%s-%s" % (sdocid[:30], datetime.now().strftime("%H%M%S"))
    return sdocid


def CalcTodoProgress(otodos):
    """批注 Todo 完成度。"""
    vitems = otodos.get("items", [])
    if not vitems:
        return {"done": 0, "total": 0, "percent": 100}
    ndone = sum(1 for x in vitems if x.get("status") == "done")
    return {"done": ndone, "total": len(vitems), "percent": int(ndone * 100 / len(vitems))}
