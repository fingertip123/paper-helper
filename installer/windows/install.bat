@echo off
chcp 65001 >nul
title Paper-Helper 安装向导
cd /d "%~dp0"

echo.
echo  ========================================
echo   Paper-Helper · 博士论文 Wiki
echo   安装向导
echo  ========================================
echo.

set "TARGET=%~dp0Paper-Helper"
if not exist "%TARGET%\Paper-Helper.exe" (
  echo [错误] 未找到 Paper-Helper\Paper-Helper.exe
  echo 请确认已完整解压 zip 包。
  pause
  exit /b 1
)

echo [1/2] 创建桌面快捷方式…
set "DESKTOP=%USERPROFILE%\Desktop"
powershell -NoProfile -Command ^
  "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%DESKTOP%\Paper-Helper.lnk');" ^
  "$s.TargetPath='%TARGET%\Paper-Helper.exe';" ^
  "$s.WorkingDirectory='%TARGET%';" ^
  "$s.Description='博士论文 Wiki';" ^
  "$s.Save()"
echo       已创建：%DESKTOP%\Paper-Helper.lnk

echo.
echo [2/2] 完成！
echo.
echo  使用方式：双击桌面「Paper-Helper」快捷方式
echo  数据目录：%USERPROFILE%\PaperHelper
echo.
echo  首次使用请在应用内 ⚙ 设置 中填写大模型 API Key。
echo.
set /p RUN="是否现在启动？(Y/n): "
if /i "%RUN%"=="n" goto :end
start "" "%TARGET%\Paper-Helper.exe"
:end
pause
