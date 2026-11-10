@echo off
REM ============================================================
REM TSE Early Warning - Force Update All Files from GitHub
REM این اسکریپت تمام فایل‌های پروژه را از GitHub به‌روزرسانی می‌کند
REM (مخصوص زمانی که git pull کار نمی‌کند)
REM ============================================================

title TSE Early Warning - Force Update

chcp 65001 >nul 2>&1

echo ============================================================
echo   TSE Early Warning - Force Update from GitHub
echo ============================================================
echo.

REM Find Python
python --version >nul 2>&1
if errorlevel 1 (
    py --version >nul 2>&1
    if errorlevel 1 (
        echo [ERROR] Python not found
        pause
        exit /b 1
    )
    set PYTHON_CMD=py
) else (
    set PYTHON_CMD=python
)

echo [INFO] This script will re-download ALL files from GitHub
echo [INFO] Your data/ and reports/ folders will be preserved
echo [INFO] Your SQLite database will be preserved
echo.
echo Press any key to continue, or Ctrl+C to cancel...
pause >nul

echo.
echo [1/4] Backing up your data...
if exist "data\early_warning_live.sqlite" (
    copy "data\early_warning_live.sqlite" "data\early_warning_live_backup.sqlite" >nul
    echo   - Backed up: data\early_warning_live.sqlite
)
echo.

echo [2/4] Downloading latest version from GitHub...
echo.

REM Create a temporary folder
if exist "_update_temp" rmdir /s /q "_update_temp"
mkdir "_update_temp"

REM Download using curl (available in Windows 10+)
echo   - Downloading ZIP from GitHub...
curl -L -o "_update_temp\repo.zip" "https://github.com/javadsekhavatpour/Sell-Buy-Queue/archive/refs/heads/main.zip" 2>nul

if not exist "_update_temp\repo.zip" (
    echo [ERROR] Failed to download from GitHub
    echo.
    echo Alternative: Download manually from:
    echo   https://github.com/javadsekhavatpour/Sell-Buy-Queue/archive/refs/heads/main.zip
    pause
    exit /b 1
)

echo [3/4] Extracting and updating files...
echo.

REM Extract using tar (available in Windows 10+)
tar -xf "_update_temp\repo.zip" -C "_update_temp" 2>nul

if not exist "_update_temp\Sell-Buy-Queue-main" (
    echo [ERROR] Extraction failed
    pause
    exit /b 1
)

REM Copy all files from extracted folder to current folder
echo   - Updating Python files...
xcopy "_update_temp\Sell-Buy-Queue-main\early_warning" "early_warning" /E /Y /I >nul
xcopy "_update_temp\Sell-Buy-Queue-main\config" "config" /E /Y /I >nul

echo   - Updating scripts...
copy "_update_temp\Sell-Buy-Queue-main\run_demo.py" "run_demo.py" >nul
copy "_update_temp\Sell-Buy-Queue-main\run_live.py" "run_live.py" >nul
copy "_update_temp\Sell-Buy-Queue-main\web_dashboard.py" "web_dashboard.py" >nul
copy "_update_temp\Sell-Buy-Queue-main\test_connection.py" "test_connection.py" >nul
copy "_update_temp\Sell-Buy-Queue-main\view_data.py" "view_data.py" >nul
copy "_update_temp\Sell-Buy-Queue-main\requirements.txt" "requirements.txt" >nul
copy "_update_temp\Sell-Buy-Queue-main\README.md" "README.md" >nul

echo   - Updating .bat files...
copy "_update_temp\Sell-Buy-Queue-main\run_web_dashboard.bat" "run_web_dashboard.bat" >nul
copy "_update_temp\Sell-Buy-Queue-main\run_web_dashboard_alt.bat" "run_web_dashboard_alt.bat" >nul
copy "_update_temp\Sell-Buy-Queue-main\run_test_connection.bat" "run_test_connection.bat" >nul

echo [4/4] Cleaning up...
rmdir /s /q "_update_temp"

echo.
echo ============================================================
echo   Update complete!
echo ============================================================
echo.
echo Files updated:
echo   - early_warning/data_collector.py (NEW v2.0)
echo   - early_warning/storage.py
echo   - early_warning/excel_report.py
echo   - early_warning/sell_pressure.py
echo   - early_warning/smart_accumulation.py
echo   - early_warning/alert_engine.py
echo   - early_warning/data_validator.py
echo   - test_connection.py (FIXED)
echo   - web_dashboard.py
echo   - All .bat scripts
echo.
echo Your data is preserved in:
echo   - data/early_warning_live.sqlite
echo.
echo Next steps:
echo   1) Run: run_test_connection.bat
echo   2) Send me the result from data\test_connection_result.txt
echo.
pause
