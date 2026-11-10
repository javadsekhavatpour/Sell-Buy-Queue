@echo off
REM ============================================================
REM TSE Early Warning - Connection Test with Auto-Save
REM Runs test, saves output to file, opens in Notepad
REM ============================================================

title TSE Early Warning - Connection Test

chcp 65001 >nul 2>&1

echo ============================================================
echo   TSE Early Warning - TSETMC Connection Test
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

echo [INFO] Running connection test...
echo [INFO] Output will be saved to: data\test_connection_result.txt
echo [INFO] The result file will open in Notepad automatically.
echo [INFO] Window will stay open - you can read everything.
echo.

%PYTHON_CMD% test_connection.py --debug

echo.
echo ============================================================
echo   Test finished.
echo   Result file: data\test_connection_result.txt
echo ============================================================
echo.

REM Open result file in Notepad for easy copy
if exist "data\test_connection_result.txt" (
    echo [INFO] Opening result file in Notepad...
    start notepad "data\test_connection_result.txt"
) else (
    echo [WARNING] Result file not found
)

echo.
echo Press any key to close this window...
pause >nul
