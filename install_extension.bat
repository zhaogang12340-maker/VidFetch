@echo off
echo Registering VidFetch native messaging host for Chrome and Edge...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_extension.ps1"
echo.
pause
