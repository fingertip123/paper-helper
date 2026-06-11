#!/bin/bash
# 兼容入口：转发到 Paper-Helper.app（与 Windows start.bat 行为一致）
cd "$(dirname "$0")" || exit 0
if [ ! -d "Paper-Helper.app" ]; then
  command -v python3 >/dev/null 2>&1 && python3 tools/make_launcher.py
fi
open "$(pwd)/Paper-Helper.app" 2>/dev/null
