#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""应用运行时上下文：集中管理 host/port/模式等，替代 app 模块级散落全局变量。"""
from dataclasses import dataclass
from typing import Callable, Optional


@dataclass
class AppContext:
    host: str = "127.0.0.1"
    port: int = 8765
    desktopmode: bool = False
    desktop_pick_folder: Optional[Callable] = None
    multiuser: bool = False
    llmdailylimit: int = 0
    baseroot: str = ""
    pdf_max_serve_bytes: int = 150 * 1024 * 1024
    pdf_serve_chunk: int = 256 * 1024
    max_body_bytes: int = 160 * 1024 * 1024
    max_upload_bytes: int = 150 * 1024 * 1024


ctx = AppContext()


def Init(baseroot, bmulti=False):
    ctx.baseroot = baseroot or ""
    ctx.multiuser = bool(bmulti)
