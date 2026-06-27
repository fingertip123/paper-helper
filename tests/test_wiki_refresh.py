#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import wiki_core as core
import wiki_refresh as refresh
import wiki_query as wquery


class TestWikiRefresh(unittest.TestCase):
    def test_get_wiki_data_cached(self):
        refresh.InvalidateWikiCache()
        o1 = refresh.GetWikiData(bforce=True)
        o2 = refresh.GetWikiData()
        self.assertIs(o1, o2)
        self.assertIn("nodes", o1)
        self.assertIn("edges", o1)

    def test_refresh_wiki_single_scan(self):
        refresh.InvalidateWikiCache()
        ncalls = {"n": 0}
        orig = core.ScanWiki

        def CountScan():
            ncalls["n"] += 1
            return orig()

        core.ScanWiki = CountScan
        try:
            refresh.InvalidateWikiCache()
            refresh.RefreshWiki(bwrite_files=True, bforce=True)
            self.assertEqual(ncalls["n"], 1)
            ncalls["n"] = 0
            refresh.RefreshWiki(bwrite_files=True)
            self.assertEqual(ncalls["n"], 0)
        finally:
            core.ScanWiki = orig


class TestWikiQuery(unittest.TestCase):
    def test_expand_neighbors(self):
        vedges = [
            {"source": "a", "target": "b"},
            {"source": "b", "target": "c"},
        ]
        oseen = wquery.ExpandNeighbors(["a"], vedges, nhops=2)
        self.assertEqual(oseen.get("a"), 0)
        self.assertEqual(oseen.get("b"), 1)
        self.assertEqual(oseen.get("c"), 2)
        self.assertNotIn("d", oseen)

    def test_collect_query_context_nonempty(self):
        sctx = wquery.CollectQueryContext("研究问题 政策执行")
        self.assertIn("purpose.md", sctx)


if __name__ == "__main__":
    unittest.main()
