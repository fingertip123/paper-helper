#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""多用户数据目录梳理 / 清理工具。

背景：早前 multiuser 未真正生效期间，所有访客共享 <data>/ 顶层数据根，
内容（topics/.yanzhan/exports 等）被写到了 <data>/ 顶层，而不是每用户的
<data>/u-<uid>/ 下。修复登录隔离后，这些顶层散落内容不再被任何账号使用，
成为“孤儿”。本工具用于体检并安全归档 / 迁移 / 删除这些散落内容。

用法（建议在服务器 Bash 控制台运行）：
    python3 tools/cleanup_multiuser_data.py                 # 只读体检（默认）
    python3 tools/cleanup_multiuser_data.py --archive       # 归档到 <data>/_legacy_shared_<时间>/（可逆）
    python3 tools/cleanup_multiuser_data.py --migrate-to 1  # 把散落内容迁进 u-1（仅当 u-1 对应目录为空/缺失）
    python3 tools/cleanup_multiuser_data.py --purge         # 直接删除散落内容（不可逆，需二次确认）

    --data-dir DIR   指定数据根（默认取环境变量 YANZHAN_DATA_DIR，否则 <项目根>/data）

始终保留：users.db 与全部 u-<uid>/ 用户目录。
"""
import os
import sys
import shutil
import argparse
from datetime import datetime

# 一个“数据根”下属于用户内容的顶层条目（散落在 <data>/ 顶层即为孤儿）。
CONTENT_ENTRIES = ("topics", ".yanzhan", ".paper-helper", "templates", "exports", "wiki", "raw")
# 始终保留、不参与清理的顶层条目。
KEEP_ENTRIES = ("users.db", "users.db-wal", "users.db-shm")


def DefaultDataDir():
    sroot = os.environ.get("YANZHAN_DATA_DIR")
    if sroot:
        return sroot
    sproj = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(sproj, "data")


def IsUserDir(sname):
    return sname.startswith("u-") and sname[2:].isdigit()


def ScanDataDir(sdatadir):
    """返回 (vusers, vstray, vother)：用户目录、散落共享内容、其它未知条目。"""
    vusers, vstray, vother = [], [], []
    for sname in sorted(os.listdir(sdatadir)):
        if sname in KEEP_ENTRIES:
            continue
        if IsUserDir(sname):
            vusers.append(sname)
        elif sname in CONTENT_ENTRIES:
            vstray.append(sname)
        elif sname.startswith("_legacy_shared_"):
            continue  # 本工具历史归档，跳过
        else:
            vother.append(sname)
    return vusers, vstray, vother


def DirSummary(spath):
    """统计目录下文件数与总字节，用于体检报告。"""
    nfiles, nbytes = 0, 0
    if os.path.isfile(spath):
        return 1, os.path.getsize(spath)
    for sdir, _, vfiles in os.walk(spath):
        for sf in vfiles:
            try:
                nbytes += os.path.getsize(os.path.join(sdir, sf))
                nfiles += 1
            except OSError:
                pass
    return nfiles, nbytes


def HumanBytes(nbytes):
    nval = float(nbytes)
    for sunit in ("B", "KB", "MB", "GB"):
        if nval < 1024 or sunit == "GB":
            return "%.1f%s" % (nval, sunit)
        nval /= 1024
    return "%.1f GB" % nval


def Report(sdatadir, vusers, vstray, vother):
    print("数据根：%s" % sdatadir)
    print("-" * 60)
    print("保留 · 用户目录 %d 个：%s" % (len(vusers), "、".join(vusers) or "（无）"))
    if os.path.isfile(os.path.join(sdatadir, "users.db")):
        print("保留 · users.db（认证库）")
    print("-" * 60)
    if not vstray:
        print("散落的共享内容：无 —— 数据根已干净。")
    else:
        print("散落的共享内容（隔离修复前的遗留，当前无账号使用）：")
        for sname in vstray:
            nfiles, nbytes = DirSummary(os.path.join(sdatadir, sname))
            print("  · %-14s  %5d 个文件  %s" % (sname, nfiles, HumanBytes(nbytes)))
    if vother:
        print("-" * 60)
        print("其它未识别条目（本工具不动，请人工确认）：%s" % "、".join(vother))
    print("-" * 60)


def MovePaths(sdatadir, vstray, sdest):
    os.makedirs(sdest, exist_ok=True)
    for sname in vstray:
        ssrc = os.path.join(sdatadir, sname)
        shutil.move(ssrc, os.path.join(sdest, sname))
        print("  移动 %s → %s" % (sname, sdest))


def DoArchive(sdatadir, vstray):
    sdest = os.path.join(sdatadir, "_legacy_shared_" + datetime.now().strftime("%Y%m%d-%H%M%S"))
    MovePaths(sdatadir, vstray, sdest)
    print("已归档到：%s（确认无用后可手动删除）" % sdest)


def DoMigrate(sdatadir, vstray, nuid):
    sudir = os.path.join(sdatadir, "u-%d" % nuid)
    stopics = os.path.join(sudir, "topics")
    if os.path.isdir(stopics) and os.listdir(stopics):
        print("拒绝迁移：u-%d 已有 topics 内容，避免覆盖。请改用 --archive 后手动合并。" % nuid)
        return False
    os.makedirs(sudir, exist_ok=True)
    for sname in vstray:
        ssrc = os.path.join(sdatadir, sname)
        sdst = os.path.join(sudir, sname)
        if os.path.exists(sdst):
            print("  跳过 %s（u-%d 下已存在）" % (sname, nuid))
            continue
        shutil.move(ssrc, sdst)
        print("  迁移 %s → u-%d/" % (sname, nuid))
    print("已迁移到账号 u-%d。" % nuid)
    return True


def DoPurge(sdatadir, vstray):
    sans = input("确认永久删除以上散落内容？不可恢复。输入 yes 继续：").strip().lower()
    if sans != "yes":
        print("已取消。")
        return
    for sname in vstray:
        spath = os.path.join(sdatadir, sname)
        if os.path.isdir(spath):
            shutil.rmtree(spath, ignore_errors=True)
        else:
            try:
                os.remove(spath)
            except OSError:
                pass
        print("  已删除 %s" % sname)
    print("散落内容已清除。")


def Main():
    oparser = argparse.ArgumentParser(description="多用户数据目录梳理 / 清理")
    oparser.add_argument("--data-dir", default=DefaultDataDir())
    ogroup = oparser.add_mutually_exclusive_group()
    ogroup.add_argument("--archive", action="store_true", help="归档散落内容（可逆）")
    ogroup.add_argument("--migrate-to", type=int, metavar="UID", help="迁移散落内容到 u-<UID>")
    ogroup.add_argument("--purge", action="store_true", help="永久删除散落内容（不可逆）")
    oargs = oparser.parse_args()

    sdatadir = os.path.abspath(oargs.data_dir)
    if not os.path.isdir(sdatadir):
        print("数据根不存在：%s" % sdatadir)
        sys.exit(1)

    vusers, vstray, vother = ScanDataDir(sdatadir)
    Report(sdatadir, vusers, vstray, vother)

    if not vstray:
        return
    if oargs.archive:
        DoArchive(sdatadir, vstray)
    elif oargs.migrate_to is not None:
        DoMigrate(sdatadir, vstray, oargs.migrate_to)
    elif oargs.purge:
        DoPurge(sdatadir, vstray)
    else:
        print("以上为只读体检。加 --archive / --migrate-to UID / --purge 之一执行清理。")


if __name__ == "__main__":
    Main()
