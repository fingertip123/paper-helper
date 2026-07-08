#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P2：图谱服务、阶段状态机、DataContext、健康检查。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

import source_stage as stage
import wiki_graph as graph
import data_context as dctx
import health_check as health


class TestSourceStage(unittest.TestCase):
    def testResolveStages(self):
        self.assertEqual(stage.ResolveLibStage(False, False, False), stage.STAGE_PENDING)
        self.assertEqual(stage.ResolveLibStage(True, False, False), stage.STAGE_AWAIT_DEEP)
        self.assertEqual(stage.ResolveLibStage(True, True, False), stage.STAGE_STANDARD)
        self.assertEqual(stage.ResolveLibStage(True, True, True), stage.STAGE_DEEP)

    def testStageRank(self):
        self.assertLess(stage.StageRank(stage.STAGE_PENDING), stage.StageRank(stage.STAGE_DEEP))


class TestWikiGraph(unittest.TestCase):
    def testRunLintQuick(self):
        vnodes = [
            {"id": "a", "type": "concept"},
            {"id": "b", "type": "purpose"},
        ]
        vedges = [{"source": "a", "target": "b"}]
        olint = graph.RunLintQuick(vnodes, vedges, ndeadlinks=2)
        self.assertEqual(olint["orphans"], 0)
        self.assertEqual(olint["dead_links"], 2)

    def testLintIsClean(self):
        self.assertTrue(graph.LintIsClean({}))
        self.assertFalse(graph.LintIsClean({"orphans": [{"id": "x"}]}))


class TestDataContext(unittest.TestCase):
    def testBindInvalidates(self):
        import wiki_refresh as refresh
        refresh.InvalidateWikiCache()
        ctx = dctx.DataContext()
        self.assertTrue(os.path.isdir(ctx.WikiDir()))


class TestHealthCheck(unittest.TestCase):
    def testRunHealth(self):
        ohealth = health.RunHealthCheck(0, {})
        self.assertIn(ohealth["status"], ("ok", "degraded"))
        self.assertIn("wiki", ohealth)
        self.assertIn("tasks", ohealth)


if __name__ == "__main__":
    unittest.main()
