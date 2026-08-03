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

:: ---- Auto-Install via winget ----
echo [1/4] Python 3.11+ not detected. Trying automatic installation...
where winget >nul 2>&1
if errorlevel 1 goto :no_winget

echo [1/4] Running: winget install Python.Python.3.11
echo [1/4] This may take a few minutes...
winget install --id Python.Python.3.11 -e --accept-package-agreements --disable-interactivity
if errorlevel 1 (
    echo [1/4] winget installation failed.
    goto :python_failed
)

echo [1/4] Installation succeeded. Refreshing environment...

:: Refresh PATH from registry (captures winget-installed Python even before reboot)
for /f "usebackq tokens=2,*" %%a in (`reg query "HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment" /v PATH 2^>nul`) do set "SYS_PATH=%%b"
for /f "usebackq tokens=2,*" %%a in (`reg query HKCU\Environment /v PATH 2^>nul`) do set "USR_PATH=%%b"
set "PATH=!SYS_PATH!;!USR_PATH!;!PATH!"

:: Add common install locations explicitly
for %%d in ("!LOCALAPPDATA!\Programs\Python\Python312" "!LOCALAPPDATA!\Programs\Python\Python311" "!PROGRAMFILES!\Python312" "!PROGRAMFILES!\Python311") do (
    if exist "%%~d\python.exe" set "PATH=%%~d;%%~d\Scripts;!PATH!"
)

:: Retry detection after PATH refresh
call :py_test "python"        && goto :python_ready
call :py_test "python3"       && goto :python_ready

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
echo Please install Python 3.11+ manually, then re-run this script:
echo.
echo   Official installer:  https://www.python.org/downloads/
echo   Microsoft Store:     Search "Python 3.11"
echo.
echo   IMPORTANT: During installation, check
echo   "Add python.exe to PATH" before clicking Install.
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

:: [3/4] Install dependencies
echo [3/4] Installing dependencies (this may take a while on first run)...
pip install -r backend\requirements.txt -q
if errorlevel 1 (
    echo [ERROR] Failed to install Python dependencies.
    echo Try running manually: pip install -r backend\requirements.txt
    pause >nul
    exit /b 1
)

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

:: [4/4] Start
echo [4/4] Starting service...
echo.
echo ==========================================
echo   Service ready: http://localhost:8000
echo   Press Ctrl+C to stop
echo ==========================================
echo.
echo [Tip] For AI chat features, copy .env.example to .env and add your API key.
echo.
python backend\main.py
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
