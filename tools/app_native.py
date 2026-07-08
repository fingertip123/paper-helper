#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跨平台原生 UI 辅助（文件夹选择等）。"""
import logging
import subprocess
import sys

import app_context as actx

logger = logging.getLogger(__name__)

exportdir_cache = {}


def PickFolderNative():
    """系统原生文件夹选择（可从 HTTP 工作线程安全调用）。"""
    if actx.ctx.desktopmode and actx.ctx.desktop_pick_folder:
        try:
            spath = actx.ctx.desktop_pick_folder()
            if spath:
                return spath.rstrip("/\\")
        except Exception:
            logger.debug("desktop_pick_folder 失败", exc_info=True)
    if sys.platform == "darwin":
        try:
            r = subprocess.run(
                ["osascript", "-e", 'POSIX path of (choose folder with prompt "选择导出文件夹")'],
                capture_output=True,
                text=True,
                timeout=300,
            )
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.strip().rstrip("/")
        except (OSError, subprocess.SubprocessError, subprocess.TimeoutExpired):
            logger.debug("macOS 文件夹选择失败", exc_info=True)
    if sys.platform.startswith("win"):
        try:
            scmd = (
                "Add-Type -AssemblyName System.windows.forms; "
                "$d=New-Object System.Windows.Forms.FolderBrowserDialog; "
                "$d.Description='选择导出文件夹'; "
                "if($d.ShowDialog() -eq 'OK'){Write-Output $d.SelectedPath}"
            )
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Sta", "-Command", scmd],
                capture_output=True,
                text=True,
                timeout=300,
            )
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.strip().rstrip("\\/")
        except (OSError, subprocess.SubprocessError, subprocess.TimeoutExpired):
            logger.debug("Windows 文件夹选择失败", exc_info=True)
    try:
        r = subprocess.run(
            ["zenity", "--file-selection", "--directory", "--title=选择导出文件夹"],
            capture_output=True,
            text=True,
            timeout=300,
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip().rstrip("/")
    except (OSError, subprocess.SubprocessError, subprocess.TimeoutExpired):
        logger.debug("zenity 文件夹选择失败", exc_info=True)
    sscript = (
        "import tkinter as tk\n"
        "from tkinter import filedialog\n"
        "r=tk.Tk()\n"
        "r.withdraw()\n"
        "try:\n"
        "    r.attributes('-topmost', True)\n"
        "except Exception:\n"
        "    pass\n"
        "p=filedialog.askdirectory(title='选择导出文件夹')\n"
        "r.destroy()\n"
        "print(p or '', end='')\n"
    )
    try:
        r = subprocess.run(
            [sys.executable, "-c", sscript],
            capture_output=True,
            text=True,
            timeout=300,
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip().rstrip("/\\")
    except (OSError, subprocess.SubprocessError, subprocess.TimeoutExpired):
        logger.debug("tkinter 文件夹选择失败", exc_info=True)
    if actx.ctx.desktop_pick_folder:
        try:
            return actx.ctx.desktop_pick_folder() or ""
        except Exception:
            logger.debug("desktop_pick_folder 回退失败", exc_info=True)
    return ""
