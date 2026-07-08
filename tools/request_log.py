#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""请求级日志上下文：为每个 HTTP 请求分配 request_id。"""
import contextvars
import logging
import time
import uuid

_rid = contextvars.ContextVar("request_id", default="")
_t0 = contextvars.ContextVar("request_t0", default=0.0)

logger = logging.getLogger("yanzhan.request")


def BeginRequest(smethod, spath):
    sid = uuid.uuid4().hex[:12]
    _rid.set(sid)
    _t0.set(time.monotonic())
    logger.info("%s %s rid=%s", smethod, spath, sid)
    return sid


def CurrentId():
    return _rid.get() or ""


def WrapTarget(ftarget, srid=None):
    """后台线程入口：继承父请求的 request_id。"""
    sparent = srid or CurrentId()

    def _inner(*args, **kwargs):
        if sparent:
            _rid.set(sparent)
        return ftarget(*args, **kwargs)

    return _inner


def LogDone(smethod, spath, ncode):
    nms = int((time.monotonic() - _t0.get()) * 1000) if _t0.get() else 0
    logger.info("%s %s -> %d rid=%s %dms", smethod, spath, ncode, CurrentId(), nms)


def LogException(smethod, spath, exc):
    logger.exception("%s %s 失败 rid=%s: %s", smethod, spath, CurrentId(), exc)
