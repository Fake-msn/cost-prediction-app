@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
title Construction Cost Prediction AI System - Startup
echo ==========================================
echo   Construction Cost Prediction AI System
echo   One-Click Startup
echo ==========================================
echo.

:: =========================================================
:: [1/4] Python 3.11+ Detection & Auto-Installation
:: =========================================================
echo [1/4] Checking Python 3.11+ environment...

set "PY_CMD="

:: ---- Helper: test if a given python command passes the version check ----
call :py_test "python"        && goto :python_ready
call :py_test "py -3.11"      && goto :python_ready
call :py_test "python3"       && goto :python_ready

:: ---- Auto-Install via winget (convenience, but may not be the latest version) ----
echo [1/4] Python 3.11+ not detected.
echo.
echo   RECOMMENDED: Download the official installer from python.org
echo   https://www.python.org/downloads/
echo   (Choose Windows 64-bit, check "Add python.exe to PATH")
echo.
echo   After installation, re-run this script.
echo.
where winget >nul 2>&1
if errorlevel 1 goto :no_winget

echo [1/4] Alternatively, press Y to let winget try an automatic install.
echo [1/4] (WARNING: winget may install an older version. python.org is preferred.)
set "WINGET_CHOICE="
set /p WINGET_CHOICE="       Auto-install via winget? [y/N]: "
if /i not "!WINGET_CHOICE!"=="y" goto :python_failed

echo [1/4] Running: winget install Python.Python.3.13
echo [1/4] This may take a few minutes...
winget install --id Python.Python.3.13 -e --accept-package-agreements --disable-interactivity 2>nul
if errorlevel 1 (
    echo [1/4] Python 3.13 not found in winget, trying 3.12...
    winget install --id Python.Python.3.12 -e --accept-package-agreements --disable-interactivity 2>nul
)
if errorlevel 1 (
    echo [1/4] winget installation failed.
    echo Please download from https://www.python.org/downloads/ instead.
    goto :python_failed
)

echo [1/4] Installation succeeded. Refreshing environment...

:: Refresh PATH from registry (captures winget-installed Python even before reboot)
for /f "usebackq tokens=2,*" %%a in (`reg query "HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment" /v PATH 2^>nul`) do set "SYS_PATH=%%b"
for /f "usebackq tokens=2,*" %%a in (`reg query HKCU\Environment /v PATH 2^>nul`) do set "USR_PATH=%%b"
set "PATH=!SYS_PATH!;!USR_PATH!;!PATH!"

:: Add common install locations explicitly
for %%d in ("!LOCALAPPDATA!\Programs\Python\Python313" "!LOCALAPPDATA!\Programs\Python\Python312" "!LOCALAPPDATA!\Programs\Python\Python311" "!PROGRAMFILES!\Python313" "!PROGRAMFILES!\Python312" "!PROGRAMFILES!\Python311") do (
    if exist "%%~d\python.exe" set "PATH=%%~d;%%~d\Scripts;!PATH!"
)

:: Retry detection after PATH refresh
call :py_test "python"        && goto :python_ready
call :py_test "python3"       && goto :python_ready

:: winget installed but detection still failed
echo [1/4] Python was installed but could not be detected. You may need to reboot.
echo Please re-run this script after rebooting, or install manually from python.org
goto :python_failed

:: ---- winget unavailable ----
:no_winget
echo [1/4] winget not available (requires Windows 10 22H2+ or Windows 11).

:: ---- All attempts failed ----
:python_failed
echo.
echo ================================================================
echo [ERROR] Could not locate or install Python 3.11+.
echo.
echo This application requires Python 3.11 or later.
echo.
echo Please install Python 3.13+ from the official website, then re-run this script:
echo.
echo   Official installer:  https://www.python.org/downloads/
echo   (Choose Windows installer (64-bit), check "Add python.exe to PATH")
echo ================================================================
echo.
echo This window will stay open so you can read the error.
echo Press any key to exit...
pause >nul
exit /b 1

:: =========================================================
:: Python found - verify and continue
:: =========================================================
:python_ready
:: Final version check (safety net against PATH picking up wrong python)
%PY_CMD% -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Detected Python !PY_CMD! does not meet minimum version 3.11.
    echo Please upgrade or install Python 3.11+ and ensure it appears first in PATH.
    goto :python_failed
)

%PY_CMD% --version
for /f "tokens=*" %%v in ('%PY_CMD% -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')"') do echo [1/4] Python %%v ready  [command: !PY_CMD!]

:: ---- Create venv if missing ----
if not exist "venv\Scripts\activate.bat" (
    echo [1/4] Creating virtual environment...
    %PY_CMD% -m venv venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment.
        echo Check that python3-venv or the equivalent is installed.
        pause >nul
        exit /b 1
    )
)

:: [2/4] Activate venv
echo [2/4] Activating virtual environment...
call venv\Scripts\activate.bat
if errorlevel 1 (
    echo [ERROR] Failed to activate virtual environment.
    pause >nul
    exit /b 1
)

:: Upgrade pip in venv (ensures pip is available and up-to-date)
echo [2/4] Upgrading pip...
python -m pip install --upgrade pip -q

:: [3/4] Install dependencies
echo [3/4] Installing dependencies (this may take a while on first run)...
echo.
python -m pip install -r backend\requirements.txt
if errorlevel 1 (
    echo.
    echo [ERROR] Failed to install Python dependencies.
    echo Try running manually: python -m pip install -r backend\requirements.txt
    pause >nul
    exit /b 1
)
echo.

:: Check bundled models (included in release package)
if not exist "models_cache\*.joblib" (
    echo [ERROR] No trained models found in models_cache\.
    echo Please ensure models_cache\ contains the .joblib files from the release.
    pause >nul
    exit /b 1
)

:: Check Tesseract (optional, with Chinese language pack detection)
where tesseract >nul 2>&1
if errorlevel 1 (
    echo [WARNING] Tesseract OCR not found - OCR for scanned PDFs unavailable.
    echo Download: https://github.com/UB-Mannheim/tesseract/wiki
    echo IMPORTANT: During installation, select Chinese (Simplified) language data.
) else (
    tesseract --list-langs 2>nul | findstr /c:"chi_sim" >nul 2>&1
    if errorlevel 1 (
        echo [WARNING] Tesseract found but Chinese language pack (chi_sim) is missing.
        echo Re-run Tesseract installer and check "Chinese (Simplified)" language data.
        echo Download: https://github.com/UB-Mannheim/tesseract/wiki
    ) else (
        echo [OK] Tesseract OCR (with Chinese language pack) ready.
    )
)

:: ---- DuckDB integrity check (NON-DESTRUCTIVE - preserves training data) ----
if exist "data\cost_prediction.duckdb" (
    echo [CHECK] Verifying DuckDB database...
    python -c "import duckdb,os; db='data/cost_prediction.duckdb'; s=os.path.getsize(db); c=duckdb.connect(db,read_only=True); b=c.execute('SELECT COUNT(*) FROM boq_items').fetchone()[0]; m=c.execute('SELECT COUNT(*) FROM project_meta').fetchone()[0]; c.close(); print(f'{s}|{b}|{m}')" > "%TEMP%\cpa_db.txt" 2>&1
    if errorlevel 1 (
        echo.
        echo [ERROR] DuckDB database is UNREADABLE.
        echo.
        echo   !!! DATA LOSS WARNING !!!
        echo   DuckDB contains ~25x MORE training data than Excel files.
        echo   Auto-rebuilding from Excel will severely reduce model accuracy.
        echo.
        echo   If you are sure you want to move it aside and rebuild, type DELETE:
        set /p DBCONFIRM="       Confirm [type DELETE]: "
        if /i "!DBCONFIRM!"=="DELETE" (
            echo [INFO] Moving unreadable DuckDB aside for recovery - not deleting...
            ren "data\cost_prediction.duckdb" "cost_prediction.corrupt-%RANDOM%.duckdb"
            echo [INFO] Original file preserved under data\cost_prediction.corrupt-*.duckdb
        ) else (
            echo [INFO] Database preserved. Attempting to start anyway...
        )
    ) else (
        for /f "tokens=1-3 delims=|" %%a in (%TEMP%\cpa_db.txt) do (
            echo [OK] DuckDB: %%a bytes ^| boq_items=%%b ^| project_meta=%%c
        )
        del "%TEMP%\cpa_db.txt" >nul 2>&1
    )
    echo.
)

:: [4/4] Start
echo [4/4] Starting service...
echo.
echo ==========================================
echo   Starting server on http://localhost:8000
echo   Press Ctrl+C to stop
echo ==========================================
echo.
python backend\main.py
if errorlevel 1 goto :svc_error

echo.
echo ==========================================
echo   Server stopped normally.
echo ==========================================
goto :svc_done

:svc_error
echo.
echo ==========================================
echo   !!! SERVER EXITED WITH AN ERROR !!!
echo.
echo   Look at the messages ABOVE this line to find the cause.
echo.
echo   Common fixes:
echo   1. Missing models: ensure models_cache\ has .joblib files
echo   2. Database error: DO NOT blindly delete DuckDB -
echo      it contains 25x more data than Excel. First try:
echo      - Close ALL programs using the project
echo      - Reboot and re-run this script
echo   3. Port conflict: close other programs using port 8000
echo   4. Dependency issue: run manually:
echo      venv\Scripts\activate ^&^& python -m pip install -r backend\requirements.txt
echo.
echo   To see the full error, open a terminal here and run:
echo      cd /d "%~dp0" ^&^& venv\Scripts\activate ^&^& python backend\main.py
echo ==========================================

:svc_done
echo.
echo [Tip] For AI chat features, copy .env.example to .env and add your API key.
echo.
pause

:: =========================================================
:: Subroutine: test a python command against version >= 3.11
:: Usage: call :py_test "python"  (sets PY_CMD on success)
:: =========================================================
:py_test
%* -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
if errorlevel 1 exit /b 1
set "PY_CMD=%*"
exit /b 0
