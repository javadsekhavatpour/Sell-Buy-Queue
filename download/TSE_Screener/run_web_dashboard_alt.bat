@echo off
REM ============================================================
REM TSE Early Warning - Alternative Launcher (uses 'py' command)
REM Use this if 'python' command is not in PATH but 'py' is.
REM ============================================================

title TSE Early Warning - Web Dashboard (Alt)

echo ============================================================
echo   TSE Early Warning - Alternative Launcher
echo ============================================================
echo.

chcp 65001 >nul 2>&1

REM Check if py launcher exists
py --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python launcher 'py' is not installed
    echo Please install Python from https://www.python.org/downloads/
    pause
    exit /b 1
)

echo [OK] Python found:
py --version
echo.

REM Check Flask
py -c "import flask" >nul 2>&1
if errorlevel 1 (
    echo [INFO] Installing Flask...
    py -m pip install flask
    if errorlevel 1 (
        echo [ERROR] Failed to install Flask
        pause
        exit /b 1
    )
    echo [OK] Flask installed
    echo.
) else (
    echo [OK] Flask is already installed
    echo.
)

echo [INFO] Starting web dashboard at http://localhost:8050
echo [INFO] Browser will open in 3 seconds...
echo.

start "" /b cmd /c "timeout /t 3 /nobreak >nul & start http://localhost:8050"

py web_dashboard.py --port 8050

echo.
pause
