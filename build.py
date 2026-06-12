#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一键打包脚本：把桌面窗口版打包成 .app（macOS）/ .exe（Windows）。

用法：
    python build.py              # 独立版（PyInstaller，无需 Python）
    python build.py --source     # 仅打源码分发 zip（体积小，首次启动自动装依赖）

产物输出到 release/。
"""
import os
import sys
import shutil
import subprocess
import zipfile
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
VENV = os.path.join(HERE, ".venv-build")
RELEASE = os.path.join(HERE, "release")
APPNAME = "Paper-Helper"


def Run(vargs, **kwargs):
    subprocess.check_call(vargs, **kwargs)


def VenvPython():
    if sys.platform.startswith("win"):
        return os.path.join(VENV, "Scripts", "python.exe")
    return os.path.join(VENV, "bin", "python")


def EnsureVenv():
    spython = VenvPython()
    if not os.path.isfile(spython):
        print("创建打包虚拟环境…")
        Run([sys.executable, "-m", "venv", VENV])
        Run([spython, "-m", "pip", "install", "--upgrade", "pip"])
        Run([spython, "-m", "pip", "install", "-r", os.path.join(HERE, "requirements.txt")])
        Run([spython, "-m", "pip", "install", "-r", os.path.join(HERE, "requirements-build.txt")])
    return spython


def PrepareSeed(spython):
    Run([spython, os.path.join(HERE, "tools", "prepare_seed.py")])


def BuildStandalone(spython):
    PrepareSeed(spython)
    nspec = os.path.join(HERE, "paper-helper.spec")
    Run([spython, "-m", "PyInstaller", "--noconfirm", "--clean", nspec], cwd=HERE)


def SourceIncludePaths():
    """源码分发包应包含的路径（相对项目根）。"""
    vpaths = [
        "tools",
        "templates",
        "assets",
        "requirements.txt",
        "README.md",
        "Paper-Helper.app",
        "Paper-Helper.vbs",
        "start.bat",
        "start.command",
        "安装说明.txt",
    ]
    vfiles = []
    for srel in vpaths:
        sabspath = os.path.join(HERE, srel)
        if os.path.isfile(sabspath):
            vfiles.append(srel)
        elif os.path.isdir(sabspath):
            for sroot, vdirs, vnames in os.walk(sabspath):
                if "__pycache__" in sroot or ".pyc" in sroot:
                    continue
                vdirs[:] = [d for d in vdirs if d not in ("__pycache__", ".pytest_cache")]
                for sname in vnames:
                    if sname.endswith(".pyc"):
                        continue
                    vfiles.append(os.path.relpath(os.path.join(sroot, sname), HERE))
    return sorted(set(vfiles))


def BuildSourceZip():
    """生成源码分发 zip：体积小，适合微信传输；首次双击会弹窗自动安装 pip 依赖。"""
    Run([sys.executable, os.path.join(HERE, "tools", "make_launcher.py")])
    os.makedirs(RELEASE, exist_ok=True)
    sstamp = datetime.now().strftime("%Y%m%d")
    splat = "mac" if sys.platform == "darwin" else ("win" if sys.platform.startswith("win") else "linux")
    szippath = os.path.join(RELEASE, "%s-%s-source.zip" % (APPNAME, splat))
    with zipfile.ZipFile(szippath, "w", zipfile.ZIP_DEFLATED) as zf:
        for srel in SourceIncludePaths():
            zf.write(os.path.join(HERE, srel), srel)
    print("源码包：%s（%.1f MB）" % (szippath, os.path.getsize(szippath) / 1048576))
    return szippath


def PackageStandalone():
    """把 PyInstaller 产物整理到 release/ 并压缩。"""
    os.makedirs(RELEASE, exist_ok=True)
    sstamp = datetime.now().strftime("%Y%m%d")
    if sys.platform == "darwin":
        ssrc = os.path.join(HERE, "dist", APPNAME + ".app")
        if not os.path.isdir(ssrc):
            raise FileNotFoundError("未找到 %s，请先完成 PyInstaller 打包" % ssrc)
        sdst = os.path.join(RELEASE, APPNAME + ".app")
        if os.path.exists(sdst):
            shutil.rmtree(sdst)
        shutil.copytree(ssrc, sdst)
        szippath = os.path.join(RELEASE, "%s-mac-%s.zip" % (APPNAME, sstamp))
        shutil.make_archive(szippath[:-4], "zip", RELEASE, APPNAME + ".app")
        print("独立版：%s（%.1f MB）" % (szippath, os.path.getsize(szippath) / 1048576))
        TryCreateDmg(sdst)
        return szippath
    if sys.platform.startswith("win"):
        ssrc = os.path.join(HERE, "dist", APPNAME)
        if not os.path.isdir(ssrc):
            raise FileNotFoundError("未找到 %s" % ssrc)
        szippath = os.path.join(RELEASE, "%s-win-%s.zip" % (APPNAME, sstamp))
        shutil.make_archive(szippath[:-4], "zip", os.path.join(HERE, "dist"), APPNAME)
        wininstaller = os.path.join(HERE, "installer", "windows", "install.bat")
        if os.path.isfile(wininstaller):
            with zipfile.ZipFile(szippath, "a", zipfile.ZIP_DEFLATED) as zf:
                zf.write(wininstaller, "安装.bat")
                zf.write(os.path.join(HERE, "安装说明.txt"), "安装说明.txt")
        print("独立版：%s（%.1f MB）" % (szippath, os.path.getsize(szippath) / 1048576))
        return szippath
    raise RuntimeError("当前平台不支持独立版打包")


def TryCreateDmg(sapppath):
    sscript = os.path.join(HERE, "installer", "macos", "create_dmg.sh")
    if not os.path.isfile(sscript):
        return
    try:
        Run(["bash", sscript, sapppath, RELEASE], cwd=HERE)
    except Exception as e:
        print("DMG 创建跳过：%s" % e)


def Main():
    bsourceonly = "--source" in sys.argv
    if bsourceonly:
        BuildSourceZip()
        print("\n完成。将 release/ 下的 zip 通过微信发给对方即可。")
        return

    spython = EnsureVenv()
    print("正在打包独立版（体积较大，无需安装 Python）…")
    BuildStandalone(spython)
    PackageStandalone()
    print("\n同时生成源码版（体积小，适合微信）…")
    BuildSourceZip()
    print("\n打包完成，产物位于：%s" % RELEASE)
    if sys.platform == "darwin":
        print("  独立版 → Paper-Helper.app / Paper-Helper-mac-*.zip / Paper-Helper.dmg")
        print("  源码版 → Paper-Helper-mac-source.zip（需本机有 Python 3）")
    elif sys.platform.startswith("win"):
        print("  独立版 → Paper-Helper-win-*.zip（解压后运行 Paper-Helper.exe）")
        print("  源码版 → Paper-Helper-win-source.zip（需本机有 Python 3）")


if __name__ == "__main__":
    Main()
