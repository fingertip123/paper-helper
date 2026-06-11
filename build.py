#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一键打包脚本：把桌面窗口版打包成 .app（macOS）/ .exe（Windows）。

用法：
    python build.py
会自动安装运行/打包依赖，再用 paper-helper.spec 执行 PyInstaller。
产物输出到 dist/。
"""
import os
import sys
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))


def Pip(vargs):
    subprocess.check_call([sys.executable, "-m", "pip", "install", *vargs])


def EnsureDeps():
    try:
        import PySide6  # noqa: F401
        import PyInstaller  # noqa: F401
    except ImportError:
        Pip(["-r", os.path.join(HERE, "requirements.txt")])
        Pip(["-r", os.path.join(HERE, "requirements-build.txt")])


def Main():
    EnsureDeps()
    nspec = os.path.join(HERE, "paper-helper.spec")
    subprocess.check_call([sys.executable, "-m", "PyInstaller", "--noconfirm", nspec], cwd=HERE)
    ndist = os.path.join(HERE, "dist")
    print("\n打包完成，产物位于：%s" % ndist)
    if sys.platform == "darwin":
        print("  → Paper-Helper.app（拖入「应用程序」即可分发）")
    elif sys.platform.startswith("win"):
        print("  → Paper-Helper\\Paper-Helper.exe（整个文件夹一起分发）")


if __name__ == "__main__":
    Main()
