#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""新用户默认大模型配置（智谱 GLM-4-Flash）。

API Key 存放在同目录的 builtin_api_key.txt（已 gitignore，打包时由 build.py 注入）。
未在 config.json 中配置 Key 的用户将自动回落到此内置配置，不会把 Key 写入用户配置。
"""
import os
import sys

BUILTIN_LLM = {
    "base_url": "https://open.bigmodel.cn/api/paas/v4",
    "model": "glm-4-flash",
    "language": "中文",
}

_KEY_FILE = "builtin_api_key.txt"


def ResolveKeyPath():
    shere = os.path.dirname(os.path.abspath(__file__))
    if getattr(sys, "frozen", False):
        smeipass = getattr(sys, "_MEIPASS", "")
        if smeipass:
            spacked = os.path.join(smeipass, "tools", _KEY_FILE)
            if os.path.isfile(spacked):
                return spacked
    spath = os.path.join(shere, _KEY_FILE)
    if os.path.isfile(spath):
        return spath
    return ""


def LoadBuiltinApiKey():
    spath = ResolveKeyPath()
    if not spath:
        return ""
    try:
        with open(spath, "r", encoding="utf-8") as f:
            return (f.read() or "").strip()
    except OSError:
        return ""


def ShouldUseBuiltinKey(ocfg, fhasusablekey):
    if fhasusablekey(ocfg):
        return False
    if "pollinations.ai" in (ocfg.get("base_url") or ""):
        return False
    if ocfg.get("use_builtin_llm") is False:
        return False
    return bool(LoadBuiltinApiKey())


def ApplyBuiltinLlm(ocfg, fhasusablekey):
    if not ShouldUseBuiltinKey(ocfg, fhasusablekey):
        return dict(ocfg), False
    oout = dict(ocfg)
    oout["base_url"] = BUILTIN_LLM["base_url"]
    oout["model"] = BUILTIN_LLM["model"]
    if not (oout.get("language") or "").strip():
        oout["language"] = BUILTIN_LLM["language"]
    oout["api_key"] = LoadBuiltinApiKey()
    return oout, True
