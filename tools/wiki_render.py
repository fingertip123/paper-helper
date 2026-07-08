#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Wiki 可视化页面渲染（string.Template 注入，避免占位符与数据冲突）。"""
import html
import json
import os
from string import Template

import topic_manager as topics
import wiki_paths as paths
import wiki_scan as scan

_VIEWER_DIR = os.path.join(os.path.dirname(__file__), "viewer")
_TEMPLATE_PATH = os.path.join(_VIEWER_DIR, "template.html")
_APP_STATE_PATH = os.path.join(_VIEWER_DIR, "app_state.js")
_TEMPLATE_CACHE = ""
_APP_STATE_CACHE = ""


def _LoadTemplate():
    global _TEMPLATE_CACHE
    if not _TEMPLATE_CACHE:
        with open(_TEMPLATE_PATH, "r", encoding="utf-8") as f:
            _TEMPLATE_CACHE = f.read()
    return _TEMPLATE_CACHE


def _LoadAppStateJs():
    global _APP_STATE_CACHE
    if not _APP_STATE_CACHE:
        with open(_APP_STATE_PATH, "r", encoding="utf-8") as f:
            _APP_STATE_CACHE = f.read()
    return _APP_STATE_CACHE


def _JsonForScript(odata):
    return json.dumps(odata, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e")


def Render(odata, servermode=False, desktopmode=False, stheme="girly", susername="", bcloud=False, scsrf=""):
    payload = _JsonForScript(odata)
    startcmd = os.path.join(paths.rootdir, "start.command").replace("\\", "\\\\").replace('"', '\\"')
    otopicsinit = {"topics": [], "current": ""}
    if servermode:
        otopicsinit = {
            "topics": scan.TopicsWithCounts(),
            "current": topics.GetCurrentTopicId() or "",
            "purpose_fields": topics.GetPurposeFieldDefs(),
        }
    stopicsinit = _JsonForScript(otopicsinit)
    sthemeid = stheme if stheme in ("fresh", "girly", "boyish", "cool") else "girly"
    suserchip = ""
    if susername:
        sesc = html.escape(susername, quote=True)
        suserchip = (
            '<span class="userchip" title="当前账号">👤 %s'
            '<a onclick="LogoutUser()" title="退出登录">退出</a></span>' % sesc)
    stpl = Template(_LoadTemplate())
    return stpl.safe_substitute(
        APP_STATE_JS=_LoadAppStateJs(),
        DATA=payload,
        INIT_TOPICS=stopicsinit,
        INIT_THEME=json.dumps(sthemeid),
        SERVERMODE="true" if servermode else "false",
        DESKTOPMODE="true" if desktopmode else "false",
        CLOUDMODE="true" if bcloud else "false",
        CSRF=json.dumps(scsrf or ""),
        CLOUD_USER=json.dumps(susername or ""),
        USERCHIP=suserchip,
        STARTCMD=startcmd,
    )
