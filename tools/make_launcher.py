#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成双端统一程序入口（无终端窗口）。

macOS  → Yanzhan.app
Windows → Yanzhan.vbs + Yanzhan.lnk（带图标快捷方式）

开发者在项目根目录运行：  python3 tools/make_launcher.py
"""
import os
import shutil
import stat
import subprocess
import sys

rootdir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
appname = "Yanzhan"
displayname = "研栈"
configdirname = ".yanzhan"
guienv = "YANZHAN_GUI"
iconsrc_mac = os.path.join(rootdir, "assets", "icon.icns")
iconsrc_win = os.path.join(rootdir, "assets", "icon.ico")

mac_script = r"""#!/bin/bash
# Finder 启动 .app 时 PATH 极窄，必须手动补全并优先选用已装 PySide6 的 Python
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$ROOT" || exit 1
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.pyenv/shims:$HOME/.local/bin:/usr/bin:/bin:$PATH"
CONFIG_DIR="$ROOT/.yanzhan"
CACHE="$CONFIG_DIR/python.path"
mkdir -p "$CONFIG_DIR"

TestPy() {
  [ -n "$1" ] && [ -x "$1" ] && "$1" -c "import PySide6" 2>/dev/null
}

FindPy() {
  local c
  if [ -f "$CACHE" ]; then
    c=$(tr -d '\r\n' < "$CACHE")
    if TestPy "$c"; then echo "$c"; return 0; fi
  fi
  for c in \
    "${PAPER_HELPER_PYTHON:-}" \
    "/opt/homebrew/bin/python3" \
    "/usr/local/bin/python3" \
    "$HOME/.pyenv/shims/python3" \
    "$(command -v python3 2>/dev/null)" \
    "/Library/Frameworks/Python.framework/Versions/Current/bin/python3" \
    "/usr/bin/python3" \
    "$(command -v python 2>/dev/null)"; do
    if TestPy "$c"; then echo "$c" > "$CACHE"; echo "$c"; return 0; fi
  done
  for c in \
    "/opt/homebrew/bin/python3" \
    "/usr/local/bin/python3" \
    "$(command -v python3 2>/dev/null)" \
    "/usr/bin/python3"; do
    [ -n "$c" ] && [ -x "$c" ] && "$c" --version >/dev/null 2>&1 && echo "$c" && return 0
  done
  return 1
}

PY=$(FindPy)
if [ -z "$PY" ]; then
  osascript -e 'display alert "未找到 Python" message "请先安装 Python 3（https://www.python.org/downloads/）" as stop'
  exit 1
fi
export YANZHAN_GUI=1
exec "$PY" tools/entry.py
"""

win_vbs = r"""' 研栈统一入口（Windows，无控制台窗口）
Option Explicit
Dim sh, fso, root, py, cmd
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = root
sh.Environment("PROCESS")("YANZHAN_GUI") = "1"
py = FindPythonw()
If py = "" Then
  MsgBox "未找到 Python。" & vbCrLf & "请安装 Python 3 并勾选 Add to PATH。" & vbCrLf & "https://www.python.org/downloads/", vbCritical, "研栈"
  WScript.Quit 1
End If
If LCase(py) = "pyw" Or LCase(py) = "pyw.exe" Then
  cmd = "pyw -3 tools/entry.py"
Else
  cmd = """""" & py & """""" & " tools/entry.py"
End If
sh.Run cmd, 0, False

Function FindPythonw()
  Dim wsh, proc, line, candidates, c
  candidates = Array("pythonw.exe", "pyw.exe")
  For Each c In candidates
    On Error Resume Next
    Set wsh = sh.Exec("where " & c)
    If Err.Number = 0 Then
      Do While wsh.Status = 0
        WScript.Sleep 50
      Loop
      line = Trim(wsh.StdOut.ReadLine())
      If line <> "" Then
        FindPythonw = line
        Exit Function
      End If
    End If
    On Error GoTo 0
  Next
  ' py 启动器：尝试 py -3 对应的 pythonw
  On Error Resume Next
  Set wsh = sh.Exec("where py")
  If Err.Number = 0 Then
    Do While wsh.Status = 0
      WScript.Sleep 50
    Loop
    If Trim(wsh.StdOut.ReadLine()) <> "" Then
      FindPythonw = "pyw"
      Exit Function
    End If
  End If
  On Error GoTo 0
  FindPythonw = ""
End Function
"""


def MakeMacApp():
    apppath = os.path.join(rootdir, appname + ".app")
    macosdir = os.path.join(apppath, "Contents", "MacOS")
    resdir = os.path.join(apppath, "Contents", "Resources")
    launcher = os.path.join(macosdir, appname)
    plist = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key><string>%s</string>
    <key>CFBundleIconFile</key><string>icon</string>
    <key>CFBundleIdentifier</key><string>com.yanzhan.app</string>
    <key>CFBundleName</key><string>%s</string>
    <key>CFBundleDisplayName</key><string>%s</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleShortVersionString</key><string>1.0</string>
    <key>CFBundleVersion</key><string>1</string>
    <key>LSMinimumSystemVersion</key><string>10.13</string>
    <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
""" % (appname, appname, displayname)
    os.makedirs(macosdir, exist_ok=True)
    os.makedirs(resdir, exist_ok=True)
    with open(os.path.join(apppath, "Contents", "Info.plist"), "w", encoding="utf-8") as f:
        f.write(plist)
    with open(launcher, "w", encoding="utf-8", newline="\n") as f:
        f.write(mac_script)
    os.chmod(launcher, os.stat(launcher).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    if os.path.isfile(iconsrc_mac):
        shutil.copy2(iconsrc_mac, os.path.join(resdir, "icon.icns"))
    print("  macOS  → %s" % apppath)


def MakeWinLauncher():
    vbspath = os.path.join(rootdir, appname + ".vbs")
    lnkpath = os.path.join(rootdir, appname + ".lnk")
    with open(vbspath, "w", encoding="utf-8", newline="\r\n") as f:
        f.write(win_vbs)
    print("  Windows → %s" % vbspath)
    if sys.platform.startswith("win") and os.path.isfile(iconsrc_win):
        ps = (
            '$s = (New-Object -ComObject WScript.Shell).CreateShortcut("%s"); '
            '$s.TargetPath = "wscript.exe"; '
            '$s.Arguments = \'"%s"\'; '
            '$s.WorkingDirectory = "%s"; '
            '$s.IconLocation = "%s"; '
            '$s.Description = "研栈"; '
            '$s.Save()'
        ) % (lnkpath.replace("\\", "\\\\"), vbspath.replace("\\", "\\\\"),
             rootdir.replace("\\", "\\\\"), iconsrc_win.replace("\\", "\\\\"))
        subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True)
        if os.path.isfile(lnkpath):
            print("  Windows → %s（推荐双击此快捷方式）" % lnkpath)
    else:
        print("  Windows → 在 Windows 上重新运行 make_launcher.py 可生成 %s.lnk" % appname)


def Main():
    print("生成研栈程序入口：")
    MakeMacApp()
    MakeWinLauncher()
    print()
    print("使用方式：")
    print("  macOS   双击 Yanzhan.app")
    print("  Windows 双击 Yanzhan.lnk（或 Yanzhan.vbs）")


if __name__ == "__main__":
    Main()
