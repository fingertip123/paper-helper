#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统一数据上下文（P2）：选题路径绑定与 wiki 缓存失效。"""
import os

import topic_manager as topics
import wiki_paths as paths


class DataContext:
    """请求级数据根：切换选题目录并失效扫描缓存。"""

    def __init__(self, nroot=None):
        self.nroot = nroot or paths.rootdir
        if nroot:
            self.Bind(nroot)

    def Bind(self, nroot):
        if not nroot:
            return
        self.nroot = nroot
        topics.Init(nroot)
        paths.SetDataRoot(nroot)
        self.InvalidateCache()

    def InvalidateCache(self, swikidir=None):
        import wiki_refresh as refresh
        refresh.InvalidateWikiCache(swikidir or paths.wikidir)

    def RefreshWiki(self, bwrite_files=True, bforce=False):
        import wiki_refresh as refresh
        if bforce:
            self.InvalidateCache()
        return refresh.RefreshWiki(bwrite_files=bwrite_files, bforce=bforce)

    def WikiDir(self):
        return paths.wikidir

    def RawSourcesDir(self):
        return paths.rawsourcesdir

    def ConfigDir(self, sresolver=None):
        if sresolver:
            return sresolver(self.nroot)
        return os.path.join(self.nroot, ".yanzhan")
