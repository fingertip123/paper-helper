#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""app_routes 与 app_context 测试。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

import app_routes
import app_context as actx


class TestAppRoutes(unittest.TestCase):
    def testMatchGetExact(self):
        spec = app_routes.MatchGet("/api/lint")
        self.assertEqual(spec.handler, "_GetLint")

    def testMatchGetPrefix(self):
        spec = app_routes.MatchGet("/raw/sources/foo.pdf")
        self.assertEqual(spec.handler, "_serve_file")
        self.assertTrue(spec.bpass_path)

    def testMatchPost(self):
        spec = app_routes.MatchPost("/api/query")
        self.assertEqual(spec.handler, "_query")

    def testUnknownRoute(self):
        self.assertIsNone(app_routes.MatchGet("/api/nope"))


class TestAppContext(unittest.TestCase):
    def testDefaults(self):
        self.assertEqual(actx.ctx.host, "127.0.0.1")
        self.assertFalse(actx.ctx.multiuser)


if __name__ == "__main__":
    unittest.main()
