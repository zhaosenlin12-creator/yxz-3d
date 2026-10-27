@echo off
chcp 65001 >nul
title VRM 模型优化工具
color 0B

echo.
echo ============================================================
echo   宜小智 VRM 模型自动优化
echo ============================================================
echo.
echo   正在优化 yxz.vrm 模型文件...
echo   原始大小: 约 36 MB
echo   目标大小: 10-15 MB
echo.
echo ============================================================
echo.

python optimize-vrm-v2.py

if errorlevel 1 (
    color 0C
    echo.
    echo ============================================================
    echo   优化失败！
    echo ============================================================
    echo.
    echo   可能原因:
    echo   1. Python 依赖未安装: pip install trimesh
    echo   2. 模型文件不存在
    echo.
    echo   请查看上方错误信息
    echo.
    pause
) else (
    color 0A
    echo.
    echo ============================================================
    echo   优化成功！
    echo ============================================================
    echo.
    echo   请运行 START.bat 重启项目查看效果
    echo.
    pause
)
