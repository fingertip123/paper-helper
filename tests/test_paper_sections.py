#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "tools"))

from paper_sections import SplitSections, PackForIngest, PackForDeep


class TestPaperSections(unittest.TestCase):
    def test_split_and_pack_ingest(self):
        stext = (
            "Abstract\nThis is abstract.\n\n"
            "1. Introduction\nIntro text here.\n\n"
            "Methods\nWe use DiD.\n\n"
            "Results\nMain finding.\n\n"
            "Conclusion\nFinal words."
        )
        osec = SplitSections(stext)
        self.assertTrue(osec.get("abstract") or osec.get("methods"))
        spacked = PackForIngest(stext, nmax=5000)
        self.assertIn("methods", spacked.lower())
        self.assertIn("DiD", spacked)

    def test_pack_for_deep_fallback(self):
        stext = "x" * 500
        self.assertEqual(len(PackForDeep(stext, nmax=200)), 200)


if __name__ == "__main__":
    unittest.main()
