#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""应用配置读写（从 app.py 解耦，供 handlers 与后台任务使用）。"""
import json
import logging
import os

import app_scope
import builtin_llm as bllm
from io_utils import AtomicWriteJson
from llm_client import HasUsableApiKey, IsPlaceholderApiKey

logger = logging.getLogger(__name__)

VALID_THEMES = frozenset({"fresh", "girly", "boyish", "cool"})


def NormalizeTheme(stheme):
    sid = (stheme or "").strip()
    return sid if sid in VALID_THEMES else "girly"


def ConfigDefaults():
    return {
        "base_url": "https://api.openai.com/v1",
        "api_key": "",
        "model": "gpt-4o-mini",
        "language": "中文",
        "theme": "girly",
    }


def LoadConfigRaw():
    if os.path.isfile(app_scope.configpath):
        try:
            with open(app_scope.configpath, "r", encoding="utf-8") as f:
                odata = json.load(f)
                if isinstance(odata, dict):
                    return odata
        except (OSError, json.JSONDecodeError, TypeError) as e:
            logger.warning("读取 config.json 失败，将使用默认配置：%s", e)
    return {}


def ApplyConfigDefaults(oraw):
    ocfg = ConfigDefaults()
    if oraw:
        ocfg.update(oraw)
    if "theme" in ocfg:
        ocfg["theme"] = NormalizeTheme(ocfg.get("theme"))
    return ocfg


def LoadConfig():
    ocfg = ApplyConfigDefaults(LoadConfigRaw())
    omerged, _ = bllm.ApplyBuiltinLlm(ocfg, HasUsableApiKey)
    return omerged


def GetConfigForApi():
    ocfg = ApplyConfigDefaults(LoadConfigRaw())
    omerged, busing = bllm.ApplyBuiltinLlm(ocfg, HasUsableApiKey)
    return {
        "base_url": omerged.get("base_url"),
        "model": omerged.get("model"),
        "language": omerged.get("language"),
        "theme": omerged.get("theme"),
        "has_api_key": HasUsableApiKey(omerged),
        "using_builtin_llm": busing,
        "api_key": "",
    }


def GetUserTheme():
    return NormalizeTheme(LoadConfig().get("theme"))


def SaveConfig(oconfig):
    os.makedirs(app_scope.configdir, exist_ok=True)
    merged = ApplyConfigDefaults(LoadConfigRaw())
    for skey in ("base_url", "model", "language", "theme"):
        if skey in oconfig:
            merged[skey] = oconfig[skey]
    if "theme" in merged:
        merged["theme"] = NormalizeTheme(merged.get("theme"))
    if oconfig.get("clear_api_key"):
        merged["api_key"] = ""
        if "pollinations.ai" in (merged.get("base_url") or ""):
            merged["use_builtin_llm"] = False
    elif "api_key" in oconfig:
        snewkey = (oconfig.get("api_key") or "").strip()
        if not IsPlaceholderApiKey(snewkey):
            merged["api_key"] = snewkey
            merged["use_builtin_llm"] = False
    if oconfig.get("use_builtin_llm") is False:
        merged["use_builtin_llm"] = False
    opersist = {k: v for k, v in merged.items() if not str(k).startswith("_")}
    AtomicWriteJson(app_scope.configpath, opersist)
    return LoadConfig()
