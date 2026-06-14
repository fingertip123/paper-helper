@echo off
chcp 65001 >nul
title 研栈 安装向导
cd /d "%~dp0"

echo.
echo  ========================================
echo   研栈
echo   安装向导
echo  ========================================
echo.

set "TARGET=%~dp0Yanzhan"
if not exist "%TARGET%\Yanzhan.exe" (
  echo [错误] 未找到 Yanzhan\Yanzhan.exe
  echo 请确认已完整解压 zip 包。
  pause
  exit /b 1
)

echo [1/2] 创建桌面快捷方式…
set "DESKTOP=%USERPROFILE%\Desktop"
powershell -NoProfile -Command ^
  "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%DESKTOP%\研栈.lnk');" ^
  "$s.TargetPath='%TARGET%\Yanzhan.exe';" ^
  "$s.WorkingDirectory='%TARGET%';" ^
  "$s.Description='研栈';" ^
  "$s.Save()"
echo       已创建：%DESKTOP%\研栈.lnk

echo.
echo [2/2] 完成！
echo.
echo  使用方式：双击桌面「研栈」快捷方式
echo  数据目录：%USERPROFILE%\Yanzhan
echo.
echo  首次使用请在应用内 ⚙ 设置 中填写大模型 API Key。
echo.
set /p RUN="是否现在启动？(Y/n): "
if /i "%RUN%"=="n" goto :end
start "" "%TARGET%\Yanzhan.exe"
:end
pause
