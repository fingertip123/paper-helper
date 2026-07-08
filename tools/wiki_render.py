#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Wiki 可视化页面渲染。"""

import json
import os

import topic_manager as topics
import wiki_paths as paths
import wiki_scan as scan


_TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "viewer", "template.html")
_TEMPLATE_CACHE = ""

def _LoadTemplate():
    global _TEMPLATE_CACHE
    if not _TEMPLATE_CACHE:
        with open(_TEMPLATE_PATH, "r", encoding="utf-8") as f:
            _TEMPLATE_CACHE = f.read()
    return _TEMPLATE_CACHE

def Render(odata, servermode=False, desktopmode=False, stheme="girly", susername="", bcloud=False, scsrf=""):
    payload = json.dumps(odata, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e")
    startcmd = os.path.join(paths.rootdir, "start.command").replace("\\", "\\\\").replace('"', '\\"')
    otopicsinit = {"topics": [], "current": ""}
    if servermode:
        otopicsinit = {
            "topics": scan.TopicsWithCounts(),
            "current": topics.GetCurrentTopicId() or "",
            "purpose_fields": topics.GetPurposeFieldDefs(),
        }
    stopicsinit = json.dumps(otopicsinit, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e")
    sthemeid = stheme if stheme in ("fresh", "girly", "boyish", "cool") else "girly"
    suserchip = ""
    if susername:
        sesc = susername.replace("&", "&amp;").replace("<", "&lt;").replace('"', "&quot;")
        suserchip = (
            '<span class="userchip" title="当前账号">👤 %s'
            '<a onclick="LogoutUser()" title="退出登录">退出</a></span>' % sesc)
    return (_LoadTemplate()
            .replace("/*__DATA__*/", payload)
            .replace("/*__INIT_TOPICS__*/", stopicsinit)
            .replace("/*__INIT_THEME__*/", json.dumps(sthemeid))
            .replace("/*__SERVERMODE__*/", "true" if servermode else "false")
            .replace("/*__DESKTOPMODE__*/", "true" if desktopmode else "false")
            .replace("/*__CLOUDMODE__*/", "true" if bcloud else "false")
            .replace("/*__CSRF__*/", json.dumps(scsrf or ""))
            .replace("/*__CLOUD_USER__*/", json.dumps(susername or ""))
            .replace("<!--__USERCHIP__-->", suserchip)
            .replace("/*__STARTCMD__*/", startcmd))
