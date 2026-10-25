@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\create_shortcut.ps1"
if errorlevel 1 (
    echo.
    echo [Deskling] Could not create the desktop shortcut.
    pause
    exit /b 1
)
echo.
echo [Deskling] Done. The shortcut is ready on your desktop.
pause
