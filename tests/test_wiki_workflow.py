#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import wiki_workflow as wflow
import topic_manager as topics
import wiki_core as core


class TestWikiWorkflow(unittest.TestCase):
    def test_parse_outline(self):
        sout = "- [ ] 第 1 章 绪论\n- [x] 第 2 章 文献综述\n"
        vch = wflow.ParseOutlineChapters(sout)
        self.assertEqual(len(vch), 2)
        self.assertFalse(vch[0]["done"])
        self.assertTrue(vch[1]["done"])

    def test_purpose_rq_hash_changes(self):
        oa = {"rq1": "a", "rq2": "", "rq3": "", "rq4": "", "thesis": "t"}
        ob = dict(oa, rq1="b")
        self.assertNotEqual(wflow.PurposeRqHash(oa), wflow.PurposeRqHash(ob))

    def test_detect_stale_on_rq_change(self):
        oa = {"rq1": "[[rq-a]]", "rq2": "", "rq3": "", "rq4": "", "thesis": ""}
        ob = dict(oa, rq1="[[rq-b]]")
        vstale = wflow.DetectStaleSources(oa, ob)
        self.assertIsInstance(vstale, list)

    def test_fix_lint_extended_runs(self):
        self.assertTrue(hasattr(core, "_SourceCanonicalScore"))
        wflow.Init(core.wikidir)
        oresult = wflow.FixLintExtended()
        self.assertIn("lint", oresult)
        self.assertIn("removed_orphans", oresult)
        self.assertIn("stripped_dead_links", oresult)
        self.assertIn("repaired_duplicates", oresult)


if __name__ == "__main__":
    unittest.main()
