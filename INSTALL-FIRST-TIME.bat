@echo off
title 宜小智工作台 一键安装启动
cd /d "%~dp0"
echo ============================================================
echo   宜小智工作台 一键安装启动
echo   前提：已安装 Node.js 20+、Python 3.10/3.11、Git
echo   首次运行会自动安装前端 pnpm 依赖 + 后端 torch（约2GB，需联网）
echo   中途请勿关闭窗口；失败时窗口会显示原因与处理建议
echo ============================================================
echo.
echo [1/2] 检查并安装依赖...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-new-pc.ps1"
if errorlevel 1 (
    echo.
    echo 安装失败，请按上方提示安装 Node/Python/Git 后重试，或查看 README.md。
    pause
    exit /b 1
)
echo.
echo [2/2] 启动服务...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-all.ps1"
echo.
pause
