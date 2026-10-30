@echo off
REM Cartoon Print Studio - detached backend launcher
REM Used because PowerShell 5.1 Start-Process crashes when env has both Path and PATH.
setlocal
set "ROOT=%~dp0.."
set "HF_ENDPOINT=https://hf-mirror.com"
set "HF_HUB_OFFLINE=0"
set "PYTHONUNBUFFERED=1"
cd /d "%ROOT%\ai\forge-webui"
"%ROOT%\ai\forge-webui\venv\Scripts\python.exe" -m uvicorn server:app --host 127.0.0.1 --port 8000 --app-dir "%ROOT%\backend" > "%ROOT%\logs\backend.log" 2> "%ROOT%\logs\backend-err.log"
endlocal
