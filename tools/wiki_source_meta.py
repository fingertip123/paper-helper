#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""文献 URL 与 source_meta 管理（SQLite，从 source_meta.json 自动迁移）。"""

import json
import os
import re
import sqlite3
import threading
import logging
from contextlib import contextmanager

import io_utils
import topic_manager as topics
import wiki_paths as paths
import wiki_markdown as md

logger = logging.getLogger(__name__)

frontmatterpattern = md.frontmatterpattern
LIB_TAG_PREFIX = "@id:"
_sourcemetalock = threading.Lock()
_dbready = False


def SourceMetaPath():
    from app_meta import ResolveConfigDir
    return os.path.join(ResolveConfigDir(topics.GetTopicDir()), "source_meta.json")


def SourceMetaDbPath():
    from app_meta import ResolveConfigDir
    return os.path.join(ResolveConfigDir(topics.GetTopicDir()), "source_meta.db")


def _Db():
    odb = sqlite3.connect(SourceMetaDbPath(), timeout=10)
    odb.execute("PRAGMA journal_mode=WAL")
    odb.row_factory = sqlite3.Row
    return odb


@contextmanager
def _DbConn():
    odb = _Db()
    try:
        yield odb
        odb.commit()
    finally:
        odb.close()


def _EnsureSchema():
    global _dbready
    if _dbready:
        return
    with _sourcemetalock:
        if _dbready:
            return
        sdir = os.path.dirname(SourceMetaDbPath())
        os.makedirs(sdir, exist_ok=True)
        with _DbConn() as odb:
            odb.executescript(
                "CREATE TABLE IF NOT EXISTS pending_url("
                " rawfile TEXT PRIMARY KEY, url TEXT NOT NULL DEFAULT '');"
                "CREATE TABLE IF NOT EXISTS source_entry("
                " skey TEXT PRIMARY KEY, data TEXT NOT NULL);"
            )
            ncount = odb.execute("SELECT COUNT(*) FROM pending_url").fetchone()[0]
            ncount += odb.execute("SELECT COUNT(*) FROM source_entry").fetchone()[0]
            if ncount == 0:
                _MigrateFromJson(odb)
        _dbready = True


def _MigrateFromJson(odb):
    spath = SourceMetaPath()
    if not os.path.isfile(spath):
        return
    try:
        with open(spath, "r", encoding="utf-8") as f:
            ometa = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("source_meta.json 迁移失败: %s", e)
        return
    if not isinstance(ometa, dict):
        return
    for skey, oentry in ometa.items():
        if skey.startswith(LIB_TAG_PREFIX):
            sskey = skey[len(LIB_TAG_PREFIX):]
            if isinstance(oentry, dict) and oentry:
                odb.execute(
                    "INSERT OR REPLACE INTO source_entry(skey, data) VALUES(?,?)",
                    (sskey, json.dumps(oentry, ensure_ascii=False)),
                )
        elif isinstance(oentry, dict):
            surl = (oentry.get("url") or "").strip()
            if surl:
                odb.execute(
                    "INSERT OR REPLACE INTO pending_url(rawfile, url) VALUES(?,?)",
                    (skey, surl),
                )
    logger.info("已从 source_meta.json 迁移 %d 条记录到 SQLite", len(ometa))


def ReadSourceMeta():
    """读取完整元数据字典（兼容旧 JSON 结构）。"""
    _EnsureSchema()
    ometa = {}
    with _sourcemetalock, _DbConn() as odb:
        for orow in odb.execute("SELECT rawfile, url FROM pending_url"):
            ometa[orow["rawfile"]] = {"url": orow["url"]}
        for orow in odb.execute("SELECT skey, data FROM source_entry"):
            try:
                oentry = json.loads(orow["data"])
            except json.JSONDecodeError:
                oentry = {}
            if isinstance(oentry, dict):
                ometa[LIB_TAG_PREFIX + orow["skey"]] = oentry
    return ometa


def WriteSourceMeta(odata):
    """全量写入（供删除文献等批量更新场景）。"""
    _EnsureSchema()
    odata = odata or {}
    with _sourcemetalock, _DbConn() as odb:
        odb.execute("DELETE FROM pending_url")
        odb.execute("DELETE FROM source_entry")
        for skey, oentry in odata.items():
            if skey.startswith(LIB_TAG_PREFIX):
                sskey = skey[len(LIB_TAG_PREFIX):]
                if isinstance(oentry, dict) and oentry:
                    odb.execute(
                        "INSERT INTO source_entry(skey, data) VALUES(?,?)",
                        (sskey, json.dumps(oentry, ensure_ascii=False)),
                    )
            elif isinstance(oentry, dict):
                surl = (oentry.get("url") or "").strip()
                if surl:
                    odb.execute(
                        "INSERT INTO pending_url(rawfile, url) VALUES(?,?)",
                        (skey, surl),
                    )


def NormalizeUrl(surl):
    surl = (surl or "").strip()
    if not surl:
        return ""
    if not re.match(r"^https?://", surl, re.I):
        raise ValueError("链接须以 http:// 或 https:// 开头")
    return surl


def GetPendingSourceUrl(srawfile):
    _EnsureSchema()
    with _sourcemetalock, _DbConn() as odb:
        orow = odb.execute(
            "SELECT url FROM pending_url WHERE rawfile=?", (srawfile,)
        ).fetchone()
    return (orow["url"] if orow else "") or ""


def SetPendingSourceUrl(srawfile, surl):
    _EnsureSchema()
    with _sourcemetalock, _DbConn() as odb:
        if surl:
            odb.execute(
                "INSERT OR REPLACE INTO pending_url(rawfile, url) VALUES(?,?)",
                (srawfile, surl),
            )
        else:
            odb.execute("DELETE FROM pending_url WHERE rawfile=?", (srawfile,))


def FindSourcePagePath(skey):
    spath = os.path.join(paths.wikidir, "sources", skey + ".md")
    return spath if os.path.isfile(spath) else ""


def UpdateSourceFrontmatterUrl(spath, surl):
    with open(spath, "r", encoding="utf-8") as f:
        ntext = f.read()
    if not md.frontmatterpattern.match(ntext):
        return
    if re.search(r"^url:\s*", ntext, re.MULTILINE):
        if surl:
            ntext = re.sub(r"^url:\s*.+$", "url: %s" % surl, ntext, count=1, flags=re.MULTILINE)
        else:
            ntext = re.sub(r"^url:\s*.+\n", "", ntext, count=1, flags=re.MULTILINE)
    elif surl:
        ntext = re.sub(r"^(---\s*\n.*?)(---\s*\n)", r"\1url: %s\n\2" % surl, ntext, count=1, flags=re.DOTALL)
    with open(spath, "w", encoding="utf-8") as f:
        f.write(ntext)


def SetPaperUrl(surl, srawfile=None, skey=None):
    surl = NormalizeUrl(surl) if surl else ""
    if not skey and srawfile:
        skey = md.ParseSourceFilename(srawfile)["key"]
    spath = FindSourcePagePath(skey) if skey else ""
    if spath:
        UpdateSourceFrontmatterUrl(spath, surl)
    if srawfile:
        SetPendingSourceUrl(srawfile, surl)
    return {"id": skey or "", "rawfile": srawfile or "", "url": surl}


def MergePendingUrlToSource(nfilename, skey=None):
    surl = GetPendingSourceUrl(nfilename)
    if not surl:
        return
    skey = skey or md.ParseSourceFilename(nfilename)["key"]
    spath = FindSourcePagePath(skey)
    if spath:
        UpdateSourceFrontmatterUrl(spath, surl)


def ListSources():
    """列出 raw/sources 下的原始文献文件名。"""
    if not os.path.isdir(paths.rawsourcesdir):
        return []
    return [fn for fn in sorted(os.listdir(paths.rawsourcesdir))
            if fn.lower().endswith((".pdf", ".docx", ".md", ".txt")) and not fn.startswith(".")]


def GetSourceMetaEntry(skey):
    """读取单篇文献元数据条目。"""
    skey = (skey or "").strip()
    if not skey:
        return {}
    _EnsureSchema()
    with _sourcemetalock, _DbConn() as odb:
        orow = odb.execute(
            "SELECT data FROM source_entry WHERE skey=?", (skey,)
        ).fetchone()
    if not orow:
        return {}
    try:
        oentry = json.loads(orow["data"])
    except json.JSONDecodeError:
        return {}
    return oentry if isinstance(oentry, dict) else {}


def SaveSourceMetaEntry(skey, oentry):
    """写入或清除单篇文献元数据条目。"""
    skey = (skey or "").strip()
    if not skey:
        raise ValueError("缺少文献 id")
    _EnsureSchema()
    with _sourcemetalock, _DbConn() as odb:
        if oentry:
            odb.execute(
                "INSERT OR REPLACE INTO source_entry(skey, data) VALUES(?,?)",
                (skey, json.dumps(oentry, ensure_ascii=False)),
            )
        else:
            odb.execute("DELETE FROM source_entry WHERE skey=?", (skey,))


def GetLibTags(skey):
    """读取论文库自定义文件夹标签。"""
    return [str(t).strip() for t in GetSourceMetaEntry(skey).get("lib_tags", []) if str(t).strip()]


def GetLibRq(skey):
    """读取用户指定的 RQ 分组。"""
    return [str(t).strip() for t in GetSourceMetaEntry(skey).get("lib_rq", []) if str(t).strip()]


def GetLibChapter(skey):
    """读取用户指定的论文章节分组。"""
    return (GetSourceMetaEntry(skey).get("lib_chapter") or "").strip()


def SetLibTags(skey, vtags):
    """保存论文库自定义文件夹标签（保留 RQ/章节字段）。"""
    skey = (skey or "").strip()
    if not skey:
        raise ValueError("缺少文献 id")
    vclean = []
    vseen = set()
    for stag in vtags or []:
        sval = str(stag).strip()
        if not sval or sval in vseen:
            continue
        vseen.add(sval)
        vclean.append(sval)
    oentry = GetSourceMetaEntry(skey)
    if vclean:
        oentry["lib_tags"] = vclean
    elif "lib_tags" in oentry:
        del oentry["lib_tags"]
    if oentry:
        SaveSourceMetaEntry(skey, oentry)
    else:
        SaveSourceMetaEntry(skey, None)
    return vclean


def SetLibRq(skey, vrq_ids):
    """保存用户指定的 RQ 分组。"""
    skey = (skey or "").strip()
    if not skey:
        raise ValueError("缺少文献 id")
    vclean = []
    vseen = set()
    for srid in vrq_ids or []:
        sval = str(srid).strip()
        if not sval or sval in vseen:
            continue
        vseen.add(sval)
        vclean.append(sval)
    oentry = GetSourceMetaEntry(skey)
    if vclean:
        oentry["lib_rq"] = vclean
    elif "lib_rq" in oentry:
        del oentry["lib_rq"]
    if oentry:
        SaveSourceMetaEntry(skey, oentry)
    else:
        SaveSourceMetaEntry(skey, None)
    return vclean


def SetLibChapter(skey, schapter):
    """保存用户指定的论文章节分组。"""
    skey = (skey or "").strip()
    if not skey:
        raise ValueError("缺少文献 id")
    schapter = (schapter or "").strip()
    oentry = GetSourceMetaEntry(skey)
    if schapter:
        oentry["lib_chapter"] = schapter
    elif "lib_chapter" in oentry:
        del oentry["lib_chapter"]
    if oentry:
        SaveSourceMetaEntry(skey, oentry)
    else:
        SaveSourceMetaEntry(skey, None)
    return schapter


def AssignSourceGroup(skey, stype, sgroup_id, saction="add"):
    """将文献归入/移出 RQ、章节或自定义文件夹。"""
    skey = (skey or "").strip()
    sgroup_id = (sgroup_id or "").strip()
    stype = (stype or "").strip().lower()
    saction = (saction or "add").strip().lower()
    if not skey:
        raise ValueError("缺少文献 id")
    if not sgroup_id and not (stype == "chapter" and saction == "remove"):
        raise ValueError("缺少文献或分组")
    if stype not in ("rq", "chapter", "folder"):
        raise ValueError("无效分组类型")
    import wiki_workflow as wflow
    wflow.Init(paths.wikidir)
    if stype == "folder":
        vtags = GetLibTags(skey)
        if saction == "add":
            if sgroup_id not in vtags:
                vtags.append(sgroup_id)
        else:
            vtags = [t for t in vtags if t != sgroup_id]
        vclean = SetLibTags(skey, vtags)
        return {"id": skey, "type": stype, "group": sgroup_id, "tags": vclean}
    if stype == "rq":
        vrq = GetLibRq(skey)
        if saction == "add":
            if sgroup_id not in vrq:
                vrq.append(sgroup_id)
                wflow.LinkSourceToRq(skey, sgroup_id)
        else:
            vrq = [r for r in vrq if r != sgroup_id]
        vclean = SetLibRq(skey, vrq)
        return {"id": skey, "type": stype, "group": sgroup_id, "rq": vclean}
    if saction == "add":
        SetLibChapter(skey, sgroup_id)
    else:
        SetLibChapter(skey, "")
    return {"id": skey, "type": stype, "group": sgroup_id, "chapter": GetLibChapter(skey)}
