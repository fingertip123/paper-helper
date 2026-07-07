#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import doc_editor as doced
import topic_manager as topics


class TestPathSecurity(unittest.TestCase):
    def setUp(self):
        self.stmp = tempfile.mkdtemp()
        topics.Init(self.stmp)
        doced.Init(topics.GetTopicDir())

    def test_validate_doc_id_rejects_traversal(self):
        with self.assertRaises(ValueError):
            doced.ValidateDocId("../etc/passwd")
        with self.assertRaises(ValueError):
            doced.ValidateDocId("foo/bar")
        self.assertEqual(doced.ValidateDocId("my-doc-01"), "my-doc-01")

    def test_doc_dir_stays_under_docs_root(self):
        spath = doced.DocDir("valid-doc")
        self.assertTrue(spath.startswith(os.path.abspath(doced.DocsDir())))
        with self.assertRaises(ValueError):
            doced.DocDir("../../config")

    def test_validate_topic_id_rejects_traversal(self):
        with self.assertRaises(ValueError):
            topics.ValidateTopicId("../templates")
        with self.assertRaises(ValueError):
            topics.ValidateTopicId("foo.bar")
        self.assertEqual(topics.ValidateTopicId("default"), "default")
        self.assertEqual(topics.ValidateTopicId("topic-20260707-204700"), "topic-20260707-204700")

    def test_get_topic_dir_stays_under_topics_root(self):
        spath = topics.GetTopicDir("default")
        self.assertTrue(spath.startswith(os.path.abspath(topics.TopicsDir())))
        with self.assertRaises(ValueError):
            topics.GetTopicDir("../../outside")


if __name__ == "__main__":
    unittest.main()
