@echo off
REM ============================================================
REM TSE Early Warning - One-Click Update from GitHub
REM ============================================================
REM این اسکریپت با یک کلیک:
REM   ۱. تمام فایل‌های پروژه را از GitHub دانلود می‌کند
REM   ۲. فایل‌های قدیمی را جایگزین می‌کند
REM   ۳. داده‌های شما (SQLite database) را حفظ می‌کند
REM   ۴. نسخه‌های فعلی را نمایش می‌دهد
REM ============================================================

title TSE Early Warning - One-Click Update

chcp 65001 >nul 2>&1

echo ============================================================
echo   TSE Early Warning - One-Click Update from GitHub
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

echo [INFO] Python: %PYTHON_CMD%
echo.

REM Step 1: Backup database
echo [1/5] Backing up your data...
if exist "data\early_warning_live.sqlite" (
    copy "data\early_warning_live.sqlite" "data\early_warning_live_backup.sqlite" >nul 2>nul
    echo   - Backed up database
)
echo.

REM Step 2: Download latest ZIP from GitHub
echo [2/5] Downloading latest version from GitHub...

if exist "_update_temp" rmdir /s /q "_update_temp"
mkdir "_update_temp"

curl -L -o "_update_temp\repo.zip" "https://github.com/javadsekhavatpour/Sell-Buy-Queue/archive/refs/heads/main.zip" 2>nul

if not exist "_update_temp\repo.zip" (
    echo [ERROR] Failed to download from GitHub
    echo.
    echo Check your internet connection
    pause
    exit /b 1
)

echo   - Downloaded ZIP file
echo.

REM Step 3: Extract
echo [3/5] Extracting files...
tar -xf "_update_temp\repo.zip" -C "_update_temp" 2>nul

if not exist "_update_temp\Sell-Buy-Queue-main" (
    echo [ERROR] Extraction failed
    pause
    exit /b 1
)

echo   - Extracted successfully
echo.

REM Step 4: Update all files
echo [4/5] Updating all files...

echo   - Updating early_warning/ folder...
xcopy "_update_temp\Sell-Buy-Queue-main\early_warning" "early_warning" /E /Y /I >nul 2>nul

echo   - Updating config/ folder...
xcopy "_update_temp\Sell-Buy-Queue-main\config" "config" /E /Y /I >nul 2>nul

echo   - Updating root Python files...
copy "_update_temp\Sell-Buy-Queue-main\run_demo.py" "run_demo.py" >nul 2>nul
copy "_update_temp\Sell-Buy-Queue-main\run_live.py" "run_live.py" >nul 2>nul
copy "_update_temp\Sell-Buy-Queue-main\web_dashboard.py" "web_dashboard.py" >nul 2>nul
copy "_update_temp\Sell-Buy-Queue-main\test_connection.py" "test_connection.py" >nul 2>nul
copy "_update_temp\Sell-Buy-Queue-main\view_data.py" "view_data.py" >nul 2>nul
copy "_update_temp\Sell-Buy-Queue-main\find_symbol_code.py" "find_symbol_code.py" >nul 2>nul
copy "_update_temp\Sell-Buy-Queue-main\search_riton.py" "search_riton.py" >nul 2>nul
copy "_update_temp\Sell-Buy-Queue-main\check_version.py" "check_version.py" >nul 2>nul
copy "_update_temp\Sell-Buy-Queue-main\update_data_collector.py" "update_data_collector.py" >nul 2>nul
copy "_update_temp\Sell-Buy-Queue-main\requirements.txt" "requirements.txt" >nul 2>nul
copy "_update_temp\Sell-Buy-Queue-main\README.md" "README.md" >nul 2>nul
copy "_update_temp\Sell-Buy-Queue-main\.gitignore" ".gitignore" >nul 2>nul
copy "_update_temp\Sell-Buy-Queue-main\LICENSE" "LICENSE" >nul 2>nul

echo   - Updating .bat scripts...
copy "_update_temp\Sell-Buy-Queue-main\run_web_dashboard.bat" "run_web_dashboard.bat" >nul 2>nul
copy "_update_temp\Sell-Buy-Queue-main\run_web_dashboard_alt.bat" "run_web_dashboard_alt.bat" >nul 2>nul
copy "_update_temp\Sell-Buy-Queue-main\run_test_connection.bat" "run_test_connection.bat" >nul 2>nul
copy "_update_temp\Sell-Buy-Queue-main\update_from_github.bat" "update_from_github.bat" >nul 2>nul

echo   - All files updated
echo.

REM Step 5: Cleanup
echo [5/5] Cleaning up temporary files...
rmdir /s /q "_update_temp"
echo   - Done
echo.

REM Final verification
echo ============================================================
echo   Update complete!
echo ============================================================
echo.

REM Verify data_collector.py version
echo Checking data_collector.py version...
%PYTHON_CMD% -c "import os; f=open('early_warning/data_collector.py','r',encoding='utf-8'); c=f.read(); f.close(); print('NEW version (cdn.tsetmc.com)' if 'cdn.tsetmc.com' in c else 'OLD version'); print('Size:', os.path.getsize('early_warning/data_collector.py'), 'bytes')"
echo.

echo ============================================================
echo   What to do next:
echo ============================================================
echo.
echo   1) Test connection to TSETMC:
echo        run_test_connection.bat
echo.
echo   2) Find code for ریتون symbol:
echo        %PYTHON_CMD% search_riton.py
echo.
echo   3) View live dashboard in browser:
echo        run_web_dashboard.bat
echo.
echo   4) Start collecting live data:
echo        %PYTHON_CMD% run_live.py --symbol ریتون --ins-code <code_from_step_2>
echo.
echo Your database is preserved at:
echo   data\early_warning_live.sqlite
echo.
echo Backup of database at:
echo   data\early_warning_live_backup.sqlite
echo.
pause
