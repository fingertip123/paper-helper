@echo off
rem 兼容入口：转发到 Yanzhan.vbs
cd /d "%~dp0"
if not exist "Yanzhan.vbs" (
  where py >nul 2>nul && py tools\make_launcher.py >nul 2>nul
  if not exist "Yanzhan.vbs" where python >nul 2>nul && python tools\make_launcher.py >nul 2>nul
)
if exist "Yanzhan.lnk" (
  start "" "%~dp0Yanzhan.lnk"
) else if exist "Yanzhan.vbs" (
  wscript.exe "%~dp0Yanzhan.vbs"
) else (
  mshta "javascript:alert('未找到研栈启动器。请运行 python tools\\make_launcher.py');close()"
)
exit /b 0
