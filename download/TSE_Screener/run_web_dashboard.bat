@echo off
REM ============================================================
REM اسکریپت اجرای داشبورد وب TSE Early Warning
REM این اسکریپت:
REM   1. encoding کنسول را به UTF-8 تنظیم می‌کند
REM   2. Flask را نصب می‌کند (اگر نصب نیست)
REM   3. سرور وب را روی پورت 8050 اجرا می‌کند
REM   4. مرورگر را به‌صورت خودکار باز می‌کند
REM ============================================================

chcp 65001 >nul
title TSE Early Warning - Web Dashboard

echo ============================================================
echo   TSE Early Warning Engine - راه‌اندازی داشبورد وب
echo ============================================================
echo.

REM بررسی نصب Flask
python -c "import flask" 2>nul
if errorlevel 1 (
    echo [نصب] Flask در حال نصب...
    pip install flask
    if errorlevel 1 (
        echo [خطا] نصب Flask ناموفق بود
        pause
        exit /b 1
    )
    echo.
)

echo [راه‌اندازی] سرور وب در حال اجرا...
echo.
echo [نکته] مرورگر به‌صورت خودکار باز می‌شود
echo [نکته] برای توقف، این پنجره را ببندید یا Ctrl+C را فشار دهید
echo.

REM باز کردن مرورگر پس از ۳ ثانیه (در پس‌زمینه)
start /b cmd /c "timeout /t 3 /nobreak >nul && start http://localhost:8050"

REM اجرای سرور وب
python web_dashboard.py --port 8050

pause
