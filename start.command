#!/bin/bash
# 博士论文 Wiki 启动器（macOS：双击本文件即可）
# 首次启动会自动安装依赖（需联网），之后启动很快。

cd "$(dirname "$0")" || exit 1

echo "======================================"
echo "  博士论文 Wiki 启动中…"
echo "======================================"

if ! command -v python3 >/dev/null 2>&1; then
  echo "未检测到 python3，请先安装 Python 3（https://www.python.org/downloads/）。"
  read -r -p "按回车键退出…" _
  exit 1
fi

echo "正在检查依赖（首次需联网安装，请稍候）…"
python3 -m pip install -r requirements.txt --quiet --disable-pip-version-check 2>/dev/null \
  || python3 -m pip install -r requirements.txt --user

echo "启动服务，浏览器将自动打开。关闭此窗口即停止服务。"
python3 tools/app.py

read -r -p "服务已停止，按回车键退出…" _
