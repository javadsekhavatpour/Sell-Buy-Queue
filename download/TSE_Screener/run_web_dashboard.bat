@echo off
REM ============================================================
REM TSE Early Warning - Web Dashboard Launcher
REM This script: 1) installs Flask if needed, 2) runs web server
REM ============================================================

title TSE Early Warning - Web Dashboard

echo ============================================================
echo   TSE Early Warning Engine - Web Dashboard Launcher
echo ============================================================
echo.

REM Change encoding to UTF-8
chcp 65001 >nul 2>&1

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed or not in PATH
    echo Please install Python from https://www.python.org/downloads/
    pause
    exit /b 1
)

echo [OK] Python found:
python --version
echo.

REM Check if Flask is installed
python -c "import flask" >nul 2>&1
if errorlevel 1 (
    echo [INFO] Flask is not installed. Installing now...
    echo.
    python -m pip install flask
    if errorlevel 1 (
        echo.
        echo [ERROR] Failed to install Flask
        echo Please run manually: python -m pip install flask
        pause
        exit /b 1
    )
    echo.
    echo [OK] Flask installed successfully
    echo.
) else (
    echo [OK] Flask is already installed
    echo.
)

echo [INFO] Starting web dashboard...
echo [INFO] Server will start at: http://localhost:8050
echo [INFO] Your browser will open automatically in 3 seconds
echo [INFO] Press Ctrl+C to stop the server
echo.

REM Open browser after 3 seconds (in background)
start "" /b cmd /c "timeout /t 3 /nobreak >nul & start http://localhost:8050"

REM Run the web dashboard
python web_dashboard.py --port 8050

echo.
echo [INFO] Server stopped
pause
