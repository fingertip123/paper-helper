# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：把桌面窗口版打包为 .app（macOS）/ .exe（Windows）。

用法：
    pip install -r requirements.txt -r requirements-build.txt
    pyinstaller --noconfirm paper-helper.spec
产物在 dist/ 下。
"""
import os
import sys
from PyInstaller.utils.hooks import collect_all

ROOT = os.path.abspath(os.getcwd())
TOOLS = os.path.join(ROOT, "tools")
ASSETS = os.path.join(ROOT, "assets")
APPNAME = "Paper-Helper"

# 内置初始内容：首次运行时由 wiki_core.ResolveRootDir 播种到 ~/PaperHelper。
# 注意：这里会把仓库当前的 wiki/ 一并打包，正式出售前请替换/清空为示例内容。
seed_datas = [
    (os.path.join(ROOT, "wiki"), "seed/wiki"),
    (os.path.join(ROOT, "purpose.md"), "seed"),
    (os.path.join(ROOT, "schema.md"), "seed"),
]

# pdfminer.six 的 cmap 等数据文件需一并收集，否则 PDF 解析会缺资源。
pdf_datas, pdf_binaries, pdf_hidden = collect_all("pdfminer")

icon_mac = os.path.join(ASSETS, "icon.icns")
icon_win = os.path.join(ASSETS, "icon.ico")
icon = icon_mac if sys.platform == "darwin" else (icon_win if sys.platform.startswith("win") else None)

a = Analysis(
    [os.path.join(TOOLS, "entry.py")],
    pathex=[TOOLS],
    binaries=pdf_binaries,
    datas=seed_datas + pdf_datas,
    hiddenimports=["pdfminer", "pdfminer.high_level"] + pdf_hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APPNAME,
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon=icon,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name=APPNAME,
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name=APPNAME + ".app",
        icon=icon_mac,
        bundle_identifier="com.paperhelper.app",
        info_plist={
            "CFBundleName": APPNAME,
            "CFBundleDisplayName": "博士论文 Wiki",
            "NSHighResolutionCapable": True,
        },
    )
