@echo off
rem 兼容入口：转发到 Paper-Helper.vbs（与 macOS start.command 行为一致）
cd /d "%~dp0"
if not exist "Paper-Helper.vbs" (
  where py >nul 2>nul && py tools\make_launcher.py >nul 2>nul
  if not exist "Paper-Helper.vbs" where python >nul 2>nul && python tools\make_launcher.py >nul 2>nul
)
if exist "Paper-Helper.lnk" (
  start "" "%~dp0Paper-Helper.lnk"
) else if exist "Paper-Helper.vbs" (
  wscript.exe "%~dp0Paper-Helper.vbs"
) else (
  mshta "javascript:alert('未找到 Paper-Helper 启动器。请运行 python tools\\make_launcher.py');close()"
)
exit /b 0
