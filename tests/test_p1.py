#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P1：API 响应与任务队列测试。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

import api_response
import task_queue
import job_state as jobs


class TestApiResponse(unittest.TestCase):
    def testEnrichAddsSchema(self):
        oout = api_response.EnrichResponse({"status": "ok"}, 200)
        self.assertEqual(oout["schema_version"], 1)
        self.assertEqual(oout["code"], "OK")

    def testErrorCode(self):
        oout = api_response.EnrichResponse({"error": "缺少参数"}, 400)
        self.assertEqual(oout["code"], "BAD_REQUEST")


class TestTaskQueue(unittest.TestCase):
    def testGetAllKinds(self):
        oall = task_queue.GetAllTasksProgress(0)
        self.assertEqual(set(oall.keys()), set(jobs.TASK_KINDS))

    def testInvalidKind(self):
        self.assertIsNone(task_queue.GetTaskProgress("invalid", 0))


if __name__ == "__main__":
    unittest.main()
