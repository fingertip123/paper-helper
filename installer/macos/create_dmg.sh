#!/bin/bash
# 将 Yanzhan.app 封装为 DMG（需 macOS + hdiutil）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
APP_SRC="${1:-$ROOT/release/Yanzhan.app}"
OUT_DIR="${2:-$ROOT/release}"
APPNAME="Yanzhan"
DMG_TMP="$OUT_DIR/.dmg-staging"
DMG_OUT="$OUT_DIR/${APPNAME}.dmg"

if [ ! -d "$APP_SRC" ]; then
  echo "未找到 $APP_SRC"
  exit 1
fi

rm -rf "$DMG_TMP" "$DMG_OUT"
mkdir -p "$DMG_TMP"
cp -R "$APP_SRC" "$DMG_TMP/"
ln -s /Applications "$DMG_TMP/Applications"
cp "$ROOT/安装说明.txt" "$DMG_TMP/" 2>/dev/null || true

hdiutil create -volname "研栈" -srcfolder "$DMG_TMP" -ov -format UDZO "$DMG_OUT"
rm -rf "$DMG_TMP"
nsize=$(du -h "$DMG_OUT" | awk '{print $1}')
echo "DMG created: $DMG_OUT ($nsize)"
