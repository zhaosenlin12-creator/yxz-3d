@echo off
chcp 936 >nul
title 宜小智工作台 - 停止服务
cd /d "%~dp0"

echo ============================================================
echo   宜小智工作台 - 停止全部服务并清理进程
echo ============================================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop-all.ps1" %*

echo.
echo 已停止。确认可以重新启动（跑「一键部署并启动.bat」）。
echo.
pause
