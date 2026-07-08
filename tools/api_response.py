#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HTTP API 响应契约：schema_version、错误码、统一封装。"""
SCHEMA_VERSION = 1

# 业务 status 与机器可读 code 的常见映射
STATUS_CODES = {
    "need_key": "NEED_API_KEY",
    "busy": "LLM_BUSY",
    "no_pending": "NO_PENDING_SOURCES",
    "started": "TASK_STARTED",
    "running": "TASK_RUNNING",
    "error": "TASK_ERROR",
    "ok": "OK",
}


def InferErrorCode(nhttp, serror="", sstatus=""):
    """根据 HTTP 状态与文案推断 error code。"""
    if sstatus and sstatus in STATUS_CODES:
        return STATUS_CODES[sstatus]
    if nhttp == 401:
        return "UNAUTHORIZED"
    if nhttp == 403:
        return "FORBIDDEN"
    if nhttp == 404:
        return "NOT_FOUND"
    if nhttp == 413:
        return "PAYLOAD_TOO_LARGE"
    if nhttp >= 500:
        return "INTERNAL_ERROR"
    if nhttp == 400:
        return "BAD_REQUEST"
    return "ERROR"


def EnrichResponse(body, nhttp=200):
    """为 JSON 响应体注入 schema_version；错误响应补全 code 字段。"""
    if not isinstance(body, dict):
        return body
    oout = dict(body)
    if "schema_version" not in oout:
        oout["schema_version"] = SCHEMA_VERSION
    if nhttp >= 400 and "error" in oout and "code" not in oout:
        oout["code"] = InferErrorCode(nhttp, oout.get("error", ""), oout.get("status", ""))
    elif "status" in oout and "code" not in oout:
        scode = STATUS_CODES.get(oout["status"])
        if scode:
            oout["code"] = scode
    return oout


def ErrorBody(smessage, scode="BAD_REQUEST", **extra):
    """构造标准错误 JSON 体（配合 HTTP 4xx/5xx）。"""
    oout = {"error": smessage, "code": scode, "schema_version": SCHEMA_VERSION}
    oout.update(extra)
    return oout
