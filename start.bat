@echo off
chcp 65001 >nul
echo ==========================================
echo   Construction Cost Prediction AI System
echo   One-Click Startup
echo ==========================================
echo.

:: =========================================================
:: [1/4] Python 3.11+ Detection & Auto-Installation
:: =========================================================
echo [1/4] Checking Python 3.11+ environment...

:: ---- Attempt 1: python ----
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
if not errorlevel 1 (
    set "PY_CMD=python"
    goto :python_ready
)

:: ---- Attempt 2: Windows Python launcher ----
py -3.11 -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
if not errorlevel 1 (
    set "PY_CMD=py -3.11"
    goto :python_ready
)

:: ---- Attempt 3: python3 ----
python3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
if not errorlevel 1 (
    set "PY_CMD=python3"
    goto :python_ready
)

:: ---- Auto-Install via winget ----
echo [1/4] Python 3.11+ not detected. Trying automatic installation...
where winget >nul 2>&1
if not errorlevel 1 (
    echo [1/4] Running: winget install Python.Python.3.11
    echo [1/4] This may take a few minutes...
    winget install --id Python.Python.3.11 -e --accept-package-agreements --disable-interactivity
    if not errorlevel 1 (
        echo [1/4] Installation succeeded. Setting up PATH...
        :: Refresh PATH with common Python 3.11/3.12 install locations
        for %%d in ("%LOCALAPPDATA%\Programs\Python\Python312" "%LOCALAPPDATA%\Programs\Python\Python311" "%PROGRAMFILES%\Python312" "%PROGRAMFILES%\Python311") do (
            if exist "%%~d\python.exe" set "PATH=%%~d;%%~d\Scripts;%PATH%"
        )
        python --version >nul 2>&1
        if not errorlevel 1 (
            set "PY_CMD=python"
            goto :python_ready
        )
    )
)

:: ---- All attempts failed ----
echo.
echo ================================================================
echo [ERROR] Could not locate or install Python 3.11+.
echo.
echo Please install Python 3.11+ manually, then re-run this script.
echo.
echo   Official installer:  https://www.python.org/downloads/
echo   Microsoft Store:     Search "Python 3.11"
echo.
echo   IMPORTANT: Check "Add python.exe to PATH" during install.
echo ================================================================
echo.
pause
exit /b 1

:python_ready
%PY_CMD% --version
for /f "tokens=*" %%v in ('%PY_CMD% -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')"') do echo [1/4] Python %%v ready  [%PY_CMD%]

:: ---- Create venv if missing ----
if not exist "venv\Scripts\activate.bat" (
    echo [1/4] Creating virtual environment...
    %PY_CMD% -m venv venv
)

:: [2/4] Activate venv
echo [2/4] Activating virtual environment...
call venv\Scripts\activate.bat

:: [3/4] Install dependencies
echo [3/4] Installing dependencies...
pip install -r backend\requirements.txt -q

:: Check bundled models (included in release package)
if not exist "models_cache\*.joblib" (
    echo [ERROR] No trained models in models_cache. Re-download the release package.
    pause
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
echo [提示] 如需 AI 对话功能，请复制 .env.example 为 .env 并填入 API Key
echo.
python backend\main.py
pause
