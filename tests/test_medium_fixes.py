#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import wiki_workflow as wflow
import wiki_ops as wops
import job_state as jstate


class TestMediumFixes(unittest.TestCase):
    def test_escape_bibtex_special_chars(self):
        s = wops.EscapeBibtex('Title {with} 100%')
        self.assertIn("\\{", s)
        self.assertIn("\\}", s)
        self.assertIn("\\%", s)

    def test_detect_stale_rq_only_no_links_returns_empty(self):
        oa = {"rq1": "[[rq-a]]", "rq2": "", "rq3": "", "rq4": "", "thesis": ""}
        ob = dict(oa, rq1="[[rq-b]]")
        vstale = wflow.DetectStaleSources(oa, ob)
        self.assertEqual(vstale, [])

    def test_ingest_cancelled_respects_generation(self):
        nuid = 99
        _, ngen = jstate.BeginIngestJob(nuid, running=True, cancelled=False)
        self.assertFalse(jstate.IsIngestCancelled(nuid, ngen))
        jstate.GetIngestJob(nuid)["cancelled"] = True
        self.assertTrue(jstate.IsIngestCancelled(nuid, ngen))
        self.assertTrue(jstate.IsIngestCancelled(nuid, ngen + 1))


if __name__ == "__main__":
    unittest.main()
