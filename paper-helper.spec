# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：把桌面窗口版打包为 .app（macOS）/ .exe（Windows）。

用法：
    python build.py
产物在 dist/ 下。
"""
import os
import sys
from PyInstaller.utils.hooks import collect_all

ROOT = os.path.abspath(os.getcwd())
TOOLS = os.path.join(ROOT, "tools")
ASSETS = os.path.join(ROOT, "assets")
SEED = os.path.join(ROOT, "build", "seed")
APPNAME = "Paper-Helper"

seed_datas = [(SEED, "seed")] if os.path.isdir(SEED) else []

asset_datas = []
for sname in ("icon.icns", "icon.png", "icon.ico"):
    spath = os.path.join(ASSETS, sname)
    if os.path.isfile(spath):
        asset_datas.append((spath, "assets"))

pdf_datas, pdf_binaries, pdf_hidden = collect_all("pdfminer")
# certifi 的 CA 证书包：打包后 HTTPS（大模型 API）校验所必需
certifi_datas, certifi_binaries, certifi_hidden = collect_all("certifi")
# 仅收集 WebEngine 所需组件，避免 collect_all(PySide6) 打入 QML/3D 等冗余（约 1GB+）
pyside_datas, pyside_binaries, pyside_hidden = collect_all("PySide6.QtWebEngineWidgets")

icon_mac = os.path.join(ASSETS, "icon.icns")
icon_win = os.path.join(ASSETS, "icon.ico")
icon = icon_mac if sys.platform == "darwin" else (icon_win if sys.platform.startswith("win") else None)

a = Analysis(
    [os.path.join(TOOLS, "entry.py")],
    pathex=[TOOLS],
    binaries=pdf_binaries + certifi_binaries + pyside_binaries,
    datas=seed_datas + asset_datas + pdf_datas + certifi_datas + pyside_datas,
    hiddenimports=[
        "pdfminer", "pdfminer.high_level", "certifi",
        "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineCore",
    ] + pdf_hidden + certifi_hidden + pyside_hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "PySide6.Qt3DAnimation", "PySide6.Qt3DCore", "PySide6.Qt3DExtras",
        "PySide6.Qt3DInput", "PySide6.Qt3DLogic", "PySide6.Qt3DRender",
        "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtGraphs",
        "PySide6.QtLocation", "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets",
        "PySide6.QtNetworkAuth", "PySide6.QtNfc", "PySide6.QtPositioning",
        "PySide6.QtQuick", "PySide6.QtQuick3D", "PySide6.QtQuickControls2",
        "PySide6.QtQuickWidgets", "PySide6.QtRemoteObjects", "PySide6.QtSensors",
        "PySide6.QtSerialPort", "PySide6.QtSpatialAudio", "PySide6.QtSvg",
        "PySide6.QtTextToSpeech", "PySide6.QtWebSockets", "PySide6.QtBluetooth",
        "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtOpenGLWidgets",
        "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.QtStateMachine",
        "PySide6.QtScxml", "PySide6.QtUiTools", "PySide6.QtAxContainer",
    ],
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
