@echo off
chcp 65001 >nul
title 宜小智工作台
color 0B

echo.
echo ═══════════════════════════════════════════════════════
echo   宜小智工作台 - 专业 AI 创作工作站
echo ═══════════════════════════════════════════════════════
echo.
echo   [1/2] 正在启动后端服务 (FastAPI)...
echo   [2/2] 正在启动前端界面 (Vue3 + 3D)...
echo.
echo   请稍候，浏览器将自动打开...
echo.
echo ═══════════════════════════════════════════════════════
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-all.ps1"

if errorlevel 1 (
    color 0C
    echo.
    echo ═══════════════════════════════════════════════════════
    echo   启动失败！
    echo ═══════════════════════════════════════════════════════
    echo.
    echo   常见问题排查：
    echo   1. 首次使用？请运行 "INSTALL-FIRST-TIME.bat"
    echo   2. 端口被占用？关闭其他程序后重试
    echo   3. 查看详细错误：检查 .run 文件夹中的日志
    echo.
    echo   详见 README.md 或联系技术支持
    echo.
    echo ═══════════════════════════════════════════════════════
    pause
) else (
    color 0A
    echo.
    echo ═══════════════════════════════════════════════════════
    echo   启动成功！
    echo ═══════════════════════════════════════════════════════
    echo.
    echo   前端界面: http://localhost:5199
    echo   后端 API: http://localhost:8000
    echo.
    echo   浏览器已自动打开，开始体验吧！
    echo   关闭此窗口将停止服务
    echo.
    echo ═══════════════════════════════════════════════════════
    echo.
    echo   按任意键退出...
    pause >nul
)
