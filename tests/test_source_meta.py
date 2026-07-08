#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""source_meta SQLite 存储测试。"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

import wiki_source_meta as smeta


class TestSourceMetaSqlite(unittest.TestCase):
    def setUp(self):
        self.ntmp = tempfile.mkdtemp()
        self.sjson = os.path.join(self.ntmp, "source_meta.json")
        self.sdb = os.path.join(self.ntmp, "source_meta.db")
        smeta._dbready = False

        def fakeDbPath():
            return self.sdb

        def fakeJsonPath():
            return self.sjson

        self._patchDb = fakeDbPath
        self._patchJson = fakeJsonPath
        smeta.SourceMetaDbPath = fakeDbPath
        smeta.SourceMetaPath = fakeJsonPath

    def testMigrateFromJson(self):
        with open(self.sjson, "w", encoding="utf-8") as f:
            json.dump({
                "paper-a.pdf": {"url": "https://example.com/a"},
                smeta.LIB_TAG_PREFIX + "a-2020": {"lib_tags": ["综述"], "lib_rq": ["rq1"]},
            }, f)
        smeta._EnsureSchema()
        self.assertTrue(os.path.isfile(self.sdb))
        self.assertEqual(smeta.GetPendingSourceUrl("paper-a.pdf"), "https://example.com/a")
        oentry = smeta.GetSourceMetaEntry("a-2020")
        self.assertEqual(oentry.get("lib_tags"), ["综述"])
        self.assertEqual(oentry.get("lib_rq"), ["rq1"])

    def testWriteSourceMetaBulk(self):
        smeta.WriteSourceMeta({
            smeta.LIB_TAG_PREFIX + "b-2021": {"lib_chapter": "第2章"},
            "raw-b.pdf": {"url": "https://example.com/b"},
        })
        ometa = smeta.ReadSourceMeta()
        self.assertEqual(ometa[smeta.LIB_TAG_PREFIX + "b-2021"]["lib_chapter"], "第2章")
        self.assertEqual(ometa["raw-b.pdf"]["url"], "https://example.com/b")
        smeta.WriteSourceMeta({})
        self.assertEqual(smeta.ReadSourceMeta(), {})


if __name__ == "__main__":
    unittest.main()
