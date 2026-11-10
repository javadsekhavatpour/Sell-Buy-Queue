@echo off
REM ============================================================
REM TSE Early Warning - Run Everything
REM ============================================================
REM این اسکریپت با یک کلیک:
REM   ۱. پروژه را از GitHub به‌روزرسانی می‌کند
REM   ۲. نسخه فعلی را نمایش می‌دهد
REM   ۳. تست اتصال به TSETMC انجام می‌دهد
REM   ۴. جستجوی نماد ریتون انجام می‌دهد
REM
REM برای شروع جمع‌آوری داده زنده، پس از این اسکریپت:
REM   python run_live.py --symbol ریتون --ins-code <CODE>
REM ============================================================

title TSE Early Warning - Run Everything

chcp 65001 >nul 2>&1

echo ============================================================
echo   TSE Early Warning - Complete Setup and Test
echo ============================================================
echo.

REM Step 1: Update from GitHub
echo [STEP 1/3] Updating project from GitHub...
echo.
call update_from_github.bat
echo.

REM Step 2: Check version
echo ============================================================
echo   [STEP 2/3] Checking version...
echo ============================================================
python check_version.py
echo.

REM Step 3: Find Riton code
echo ============================================================
echo   [STEP 3/3] Finding ریتون symbol code...
echo ============================================================
python search_riton.py
echo.

echo ============================================================
echo   All done!
echo ============================================================
echo.
echo To start collecting LIVE data for ریتون:
echo.
echo   1) Open data\search_riton_result.txt to find the ins_code
echo   2) Run: python run_live.py --symbol ریتون --ins-code <CODE>
echo   3) Open another window and run: run_web_dashboard.bat
echo.
pause
