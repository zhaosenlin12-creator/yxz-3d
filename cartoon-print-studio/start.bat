@echo off
setlocal
chcp 65001 > nul
title Cartoon Print Studio
cd /d "%~dp0"

echo == Starting backend ==
powershell -ExecutionPolicy Bypass -File scripts\start_backend.ps1
if errorlevel 1 (
    echo.
    echo Backend did not start. Check logs\backend-err.log for details.
    pause
    exit /b 1
)
echo Backend PID logged to logs\backend.pid

echo.
echo == Waiting for backend ready ==
:waitloop
powershell -NoProfile -Command "try { (Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 http://127.0.0.1:8000/api/health).StatusCode } catch { exit 1 }" > nul 2>&1
if errorlevel 1 (
    timeout /t 2 /nobreak > nul
    goto waitloop
)
echo Backend is ready.

echo.
echo == Opening desktop window ==
ai\forge-webui\venv\Scripts\python.exe backend\app_desktop.py

echo.
echo Window closed. Run stop.bat to fully shut down.
pause
