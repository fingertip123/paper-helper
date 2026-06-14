#!/bin/bash
# 兼容入口：转发到 Yanzhan.app
cd "$(dirname "$0")" || exit 1
if [ ! -d "Yanzhan.app" ]; then
  command -v python3 >/dev/null && python3 tools/make_launcher.py >/dev/null 2>&1
fi
open "$(pwd)/Yanzhan.app" 2>/dev/null
