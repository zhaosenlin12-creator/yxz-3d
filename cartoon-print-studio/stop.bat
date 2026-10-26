@echo off
chcp 65001 > nul
echo Stopping backend...
powershell -ExecutionPolicy Bypass -File scripts\stop_backend.ps1
taskkill /F /IM bambu-studio.exe 2> nul
echo Done.
