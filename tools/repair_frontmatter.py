#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""批量修复磁盘上 wiki 页的非法 frontmatter（如 title 含未加引号的冒号）。

复用 wiki_markdown.SanitizeFrontmatter 的修复逻辑，不重复实现。

用法（建议在服务器 Bash 控制台运行）：
    python3 tools/repair_frontmatter.py                 # 只读体检：列出所有 frontmatter 非法的页
    python3 tools/repair_frontmatter.py --apply         # 就地修复（先把原文件备份为 <file>.bak）
    python3 tools/repair_frontmatter.py 路径A 路径B ...   # 指定扫描目录（可多个）

默认扫描：环境变量 YANZHAN_DATA_DIR（或 <项目根>/data）+ <项目根>/topics，递归查找 *.md。
"""
import os
import sys
import argparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

try:
    import yaml
except ImportError:
    yaml = None

import wiki_markdown as md
from wiki_config import frontmatterpattern


def DefaultRoots():
    sproj = os.path.dirname(HERE)
    vroots = []
    sdata = os.environ.get("YANZHAN_DATA_DIR") or os.path.join(sproj, "data")
    if os.path.isdir(sdata):
        vroots.append(sdata)
    stopics = os.path.join(sproj, "topics")
    if os.path.isdir(stopics):
        vroots.append(stopics)
    return vroots or [sproj]


def IsFrontmatterValid(ntext):
    """返回 (有 frontmatter?, 是否合法)。"""
    omatch = frontmatterpattern.match(ntext)
    if not omatch:
        return False, True
    if yaml is None:
        return True, True
    try:
        yaml.safe_load(omatch.group(1))
        return True, True
    except yaml.YAMLError:
        return True, False


def IterMarkdown(vroots):
    for sroot in vroots:
        if os.path.isfile(sroot) and sroot.endswith(".md"):
            yield sroot
            continue
        for sdir, vsub, vfiles in os.walk(sroot):
            vsub[:] = [d for d in vsub if d not in (".trash", ".ingest-staging")]
            for sf in vfiles:
                if sf.endswith(".md"):
                    yield os.path.join(sdir, sf)


def RepairFile(spath, bapply):
    """返回状态："ok"（本就合法）/ "fixed" / "would_fix" / "unfixable"。"""
    with open(spath, "r", encoding="utf-8") as f:
        ntext = f.read()
    bhas, bvalid = IsFrontmatterValid(ntext)
    if not bhas or bvalid:
        return "ok"
    sfixed = md.SanitizeFrontmatter(ntext)
    _, bvalid_after = IsFrontmatterValid(sfixed)
    if not bvalid_after or sfixed == ntext:
        return "unfixable"
    if not bapply:
        return "would_fix"
    sbak = spath + ".bak"
    if not os.path.exists(sbak):
        with open(sbak, "w", encoding="utf-8") as f:
            f.write(ntext)
    with open(spath, "w", encoding="utf-8") as f:
        f.write(sfixed)
    return "fixed"


def Main():
    oparser = argparse.ArgumentParser(description="批量修复 wiki frontmatter 非法问题")
    oparser.add_argument("paths", nargs="*", help="要扫描的目录/文件（默认 data + topics）")
    oparser.add_argument("--apply", action="store_true", help="就地修复（默认只读体检）")
    oargs = oparser.parse_args()

    vroots = [os.path.abspath(p) for p in oargs.paths] or DefaultRoots()
    if yaml is None:
        print("警告：未安装 PyYAML，无法判定合法性。请先 pip install PyYAML")
        sys.exit(1)

    print("扫描：%s" % "、".join(vroots))
    print("-" * 60)
    ncount = {"ok": 0, "fixed": 0, "would_fix": 0, "unfixable": 0}
    for spath in IterMarkdown(vroots):
        sstatus = RepairFile(spath, oargs.apply)
        ncount[sstatus] += 1
        if sstatus == "fixed":
            print("✓ 已修复：%s（原文件备份为 .bak）" % spath)
        elif sstatus == "would_fix":
            print("· 可修复：%s" % spath)
        elif sstatus == "unfixable":
            print("⚠ 无法自动修复，请人工检查：%s" % spath)
    print("-" * 60)
    print("合法 %d · 已修复 %d · 可修复 %d · 需人工 %d" % (
        ncount["ok"], ncount["fixed"], ncount["would_fix"], ncount["unfixable"]))
    if ncount["would_fix"] and not oargs.apply:
        print("以上为只读体检。加 --apply 执行就地修复（会先备份 .bak）。")


if __name__ == "__main__":
    Main()
