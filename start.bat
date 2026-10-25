@echo off
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    where py >nul 2>nul
    if errorlevel 1 (
        echo [Deskling] Python was not found. Please install Python 3.10+ first.
        pause
        exit /b 1
    )
    set "PYTHON=py -3"
) else (
    set "PYTHON=python"
)

%PYTHON% -c "import PyQt6" >nul 2>nul
if errorlevel 1 (
    echo [Deskling] PyQt6 is missing. Installing requirements...
    %PYTHON% -m pip install -r requirements.txt
    if errorlevel 1 (
        echo.
        echo [Deskling] Install failed. Run debug.bat to see details.
        pause
        exit /b 1
    )
)

where pythonw >nul 2>nul
if not errorlevel 1 (
    start "" pythonw "%~dp0main.py"
    exit /b 0
)

start "" %PYTHON% "%~dp0main.py"
exit /b 0
