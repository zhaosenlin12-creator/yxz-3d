@echo off
rem 宜小智工作台 - 新电脑一键安装并启动（双击本文件即可）
title 宜小智工作台 一键安装并启动
cd /d "%~dp0"
echo ============================================
echo   宜小智工作台 一键安装并启动
echo   前提：本机已安装 Node.js 20+、Python 3.10/3.11、Git
echo   首次运行会自动安装依赖（前端 pnpm + 后端 torch，约几分钟）
echo ============================================
echo.
echo [1/2] 检查并安装依赖...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-new-pc.ps1"
if errorlevel 1 (
    echo.
    echo 安装失败，请按上方提示补装 Node/Python/Git 后重试。
    pause
    exit /b 1
)
echo.
echo [2/2] 启动服务...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-all.ps1"
echo.
pause
