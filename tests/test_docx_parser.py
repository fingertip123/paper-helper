#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""docx_parser 单元测试。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

import docx_parser as dx


class TestDocxParser(unittest.TestCase):
    def testSanitizeParaText(self):
        self.assertEqual(dx._SanitizeParaText("hello 📝 world"), "hello  world")

    def testStripHtmlTags(self):
        self.assertEqual(dx._StripHtmlTags('<span style="x">a</span>'), "a")

    def testValidateEmpty(self):
        with self.assertRaises(ValueError):
            dx._ValidateDocxBytes(b"")

    def testEscHtml(self):
        self.assertEqual(dx._EscHtml("<a&>"), "&lt;a&amp;&gt;")


class TestDocModules(unittest.TestCase):
    def testPparaCommentsMap(self):
        import doc_editor_html as dh
        omap = dh._PparaCommentsMap([
            {"id": "1", "para_index": 0, "status": "pending"},
            {"id": "2", "para_index": 1, "status": "done"},
        ], "pending")
        self.assertEqual(len(omap[0]), 1)

    def testRevHash(self):
        import doc_revisions as dr
        self.assertEqual(len(dr._RevHash("20260101-120000-123456")), 8)

    def testDocEditorFacade(self):
        import doc_editor as de
        self.assertTrue(callable(de.GetEditorHtml))
        self.assertTrue(callable(de.SaveRevision))
        self.assertTrue(callable(de._HeadRevisionId))

    def testDocApiImport(self):
        import doc_api as api
        self.assertTrue(callable(api.ImportDocx))
        self.assertTrue(callable(api.ListDocs))


if __name__ == "__main__":
    unittest.main()
