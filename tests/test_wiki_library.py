#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""论文库排序元数据测试。"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

import wiki_core as core


class TestWikiLibrary(unittest.TestCase):
    def setUp(self):
        self.ntmp = tempfile.mkdtemp()
        self.wiki = os.path.join(self.ntmp, "wiki")
        self.raw = os.path.join(self.ntmp, "raw", "sources")
        os.makedirs(os.path.join(self.wiki, "sources"), exist_ok=True)
        os.makedirs(self.raw, exist_ok=True)
        core.wikidir = self.wiki
        core.rawsourcesdir = self.raw

    def _Touch(self, spath, nsec):
        with open(spath, "w", encoding="utf-8") as f:
            f.write("x")
        import time
        os.utime(spath, (nsec, nsec))

    def testSortAuthorKey(self):
        self.assertEqual(core.SortAuthorKey({"authors": ["Zhang, Wei"]}), "zhang")
        self.assertEqual(core.SortAuthorKey({"title": "Alpha Paper"}), "alpha paper")

    def testSourceTimestamps(self):
        sraw = os.path.join(self.raw, "smith-2020-paper.pdf")
        self._Touch(sraw, 1000)
        onode = {"id": "smith-2020", "rawfile": "smith-2020-paper.pdf", "ingested": False}
        nadded, ningested = core.SourceTimestamps(onode)
        self.assertEqual(nadded, 1000)
        self.assertEqual(ningested, 0)

        spage = os.path.join(self.wiki, "sources", "smith-2020.md")
        self._Touch(spage, 2000)
        onode["ingested"] = True
        nadded, ningested = core.SourceTimestamps(onode)
        self.assertEqual(nadded, 2000)
        self.assertEqual(ningested, 2000)

    def testEnrichSourceLibraryMeta(self):
        sraw = os.path.join(self.raw, "lee-2021-test.pdf")
        self._Touch(sraw, 1500)
        spage = os.path.join(self.wiki, "sources", "lee-2021.md")
        with open(spage, "w", encoding="utf-8") as f:
            f.write("---\ntype: source\ntitle: Test\nauthors: [Lee]\nyear: 2021\n---\n\n## 摘要\nDone\n")
        import time
        os.utime(spage, (2500, 2500))
        vnodes = [{
            "id": "lee-2021", "type": "source", "title": "Test",
            "authors": ["Lee"], "year": "2021", "rawfile": "lee-2021-test.pdf",
            "ingested": True,
        }]
        core.EnrichSourceLibraryMeta(vnodes)
        n = vnodes[0]
        self.assertEqual(n["lib_stage"], "await_deep")
        self.assertEqual(n["lib_rank"], 2)
        self.assertEqual(n["added_at"], 2500)
        self.assertEqual(n["ingested_at"], 2500)
        self.assertEqual(n["sort_author"], "lee")


if __name__ == "__main__":
    unittest.main()
