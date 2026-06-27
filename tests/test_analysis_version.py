#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import sys
import tempfile
import shutil
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

import analysis_version as aver


class TestAnalysisVersion(unittest.TestCase):
    def testPipelineRegistry(self):
        self.assertIn("ingest", aver.PIPELINE_VERSIONS)
        self.assertIn("deep", aver.PIPELINE_VERSIONS)
        self.assertGreaterEqual(aver.GetCurrentVersion("ingest"), 1)

    def testOldReportIsStale(self):
        otmp = tempfile.mkdtemp()
        try:
            spath = os.path.join(otmp, "old-report.md")
            with open(spath, "w", encoding="utf-8") as f:
                f.write("---\ntype: analysis-report\npipeline: deep\npipeline_version: 1\n---\n\n# old\n")
            self.assertTrue(aver.IsPageStale(spath, "deep"))
        finally:
            shutil.rmtree(otmp)

    def testCurrentReportNotStale(self):
        otmp = tempfile.mkdtemp()
        try:
            spath = os.path.join(otmp, "new-report.md")
            with open(spath, "w", encoding="utf-8") as f:
                f.write("---\ntype: analysis-report\npipeline: deep\npipeline_version: %d\n---\n\n# new\n" % aver.GetCurrentVersion("deep"))
            self.assertFalse(aver.IsPageStale(spath, "deep"))
        finally:
            shutil.rmtree(otmp)

    def testStampMarkdownIngest(self):
        sraw = "---\ntype: source\ntitle: Test\n---\n\n# body\n"
        sout = aver.StampMarkdown(sraw, "ingest", 2)
        self.assertIn("pipeline: ingest", sout)
        self.assertIn("pipeline_version: 2", sout)

    def testPipelineForWikiPath(self):
        self.assertEqual(aver.PipelineForWikiPath("sources/foo.md"), "ingest")
        self.assertEqual(aver.PipelineForWikiPath("analysis/bar-report.md"), "deep")
        self.assertEqual(aver.PipelineForWikiPath("queries/q-1.md"), "query")


if __name__ == "__main__":
    unittest.main()
