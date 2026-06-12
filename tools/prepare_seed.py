#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成打包用干净种子目录 build/seed/（不含用户选题与测试文档）。"""
import os
import shutil

rootdir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
seeddir = os.path.join(rootdir, "build", "seed")
templatesdir = os.path.join(rootdir, "templates")

wikisubdirs = [
    "sources", "concepts", "entities", "research-questions",
    "experiments", "synthesis", "comparisons", "queries",
]


def CopyIfExists(ssrc, sdst):
    if os.path.isfile(ssrc):
        os.makedirs(os.path.dirname(sdst), exist_ok=True)
        shutil.copy2(ssrc, sdst)


def Main():
    if os.path.isdir(seeddir):
        shutil.rmtree(seeddir)
    os.makedirs(seeddir, exist_ok=True)

    for sname in ("purpose.md", "schema.md", "AGENTS.md"):
        CopyIfExists(os.path.join(templatesdir, sname), os.path.join(seeddir, sname))

    shutil.copytree(templatesdir, os.path.join(seeddir, "templates"))

    for ssub in wikisubdirs:
        stpl = os.path.join(templatesdir, "wiki", ssub, "_template.md")
        if os.path.isfile(stpl):
            sdst = os.path.join(seeddir, "wiki", ssub, "_template.md")
            os.makedirs(os.path.dirname(sdst), exist_ok=True)
            shutil.copy2(stpl, sdst)

    for sname in ("index.md", "log.md", "overview.md"):
        spath = os.path.join(seeddir, "wiki", sname)
        os.makedirs(os.path.dirname(spath), exist_ok=True)
        with open(spath, "w", encoding="utf-8") as f:
            f.write("---\ntype: meta\ntitle: %s\n---\n\n" % sname)

    os.makedirs(os.path.join(seeddir, "raw", "sources"), exist_ok=True)
    os.makedirs(os.path.join(seeddir, "raw", "assets"), exist_ok=True)
    print("种子目录已生成：%s" % seeddir)


if __name__ == "__main__":
    Main()
