#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""topic_manager 遗留数据清理测试。"""
import os
import sys
import shutil
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

import topic_manager as topics


class TestLegacyPrune(unittest.TestCase):
    def testPruneMovesRootWiki(self):
        ntmp = tempfile.mkdtemp()
        try:
            topics.Init(ntmp)
            topics.EnsureTemplates()
            ndef = os.path.join(ntmp, "topics", "default")
            os.makedirs(os.path.join(ndef, "wiki", "sources"), exist_ok=True)
            with open(os.path.join(ndef, "wiki", "sources", "a.md"), "w", encoding="utf-8") as f:
                f.write("x")
            os.makedirs(os.path.join(ntmp, "wiki", "concepts"), exist_ok=True)
            topics.PruneLegacyRootData()
            self.assertFalse(os.path.isdir(os.path.join(ntmp, "wiki")))
            self.assertTrue(os.path.isdir(os.path.join(ntmp, ".legacy", "wiki")))
        finally:
            shutil.rmtree(ntmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
