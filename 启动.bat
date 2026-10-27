@echo off
rem 宜小智工作台 - 一键启动（双击本文件即可）
title 宜小智工作台 一键启动
cd /d "%~dp0"
echo 正在启动后端(8000)与前端(5199)，请稍候...
echo 若首次运行或提示缺少依赖，请改用：一键安装并启动.bat
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-all.ps1"
echo.
pause
