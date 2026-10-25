@echo off
setlocal
cd /d "%~dp0"
python main.py --debug
echo.
echo [Deskling] exited with code %errorlevel%
pause
