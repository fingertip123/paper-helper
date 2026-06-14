#!/usr/bin/env python3
"""跨平台启动器：自动识别操作系统/Python、安装依赖、启动本地服务。

被 start.command（macOS/Linux）与 start.bat（Windows）共同调用，
也可在任意系统直接运行：  python tools/launch.py
"""

import os
import sys
import subprocess

rootdir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def OsName():
    """返回友好的操作系统名称。"""
    if sys.platform.startswith("win"):
        return "Windows"
    if sys.platform == "darwin":
        return "macOS"
    return "Linux/其他"


def DepsInstalled():
    """检查「分析」功能所需的 pdfminer 是否已可用。"""
    try:
        import pdfminer  # noqa: F401
        return True
    except Exception:
        return False


def EnsureDeps():
    """尽力安装 requirements.txt（仅「分析」功能需要；失败不阻断启动）。

    已装则跳过；未装则依次尝试多种 pip 方式，兼容 Homebrew 等 PEP 668
    "externally-managed-environment" 受管环境。
    """
    if DepsInstalled():
        return
    req = os.path.join(rootdir, "requirements.txt")
    if not os.path.isfile(req):
        return
    print("正在安装依赖（首次需联网，请稍候）…")
    base = [sys.executable, "-m", "pip", "install", "-r", req, "--quiet", "--disable-pip-version-check"]
    # 依次尝试：常规 / 用户级 / 受管环境(PEP 668) / 用户级+受管。输出静默，避免刷屏。
    for extra in ([], ["--user"], ["--break-system-packages"], ["--user", "--break-system-packages"]):
        try:
            subprocess.run(base + extra, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass
        if DepsInstalled():
            print("依赖就绪。")
            return
    print("提示：依赖未能自动安装。仅「分析」功能需要它，浏览/添加/删除/刷新不受影响。")
    print("可手动安装：%s -m pip install pdfminer.six --user" % os.path.basename(sys.executable))


def Main():
    print("=" * 42)
    print("  研栈启动中…  当前系统：%s" % OsName())
    print("=" * 42)
    EnsureDeps()
    sys.path.insert(0, os.path.join(rootdir, "tools"))
    import app  # 复用同一套服务逻辑（跨平台）
    app.Main()


if __name__ == "__main__":
    Main()
