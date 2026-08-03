@echo off
chcp 65001 >nul
echo ==========================================
echo   Construction Cost Prediction AI System
echo   One-Click Startup
echo ==========================================
echo.

:: [1/4] Check Python 3.11+
echo [1/4] Checking Python...
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python 3.11+ not found. Please install it first.
    echo Download: https://www.python.org/downloads/
    echo IMPORTANT: check "Add python.exe to PATH" during installation.
    pause
    exit /b 1
)

:: Create venv if missing
if not exist "venv\Scripts\activate.bat" (
    echo [1/4] Creating virtual environment...
    python -m venv venv
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

:: Check Tesseract (optional)
where tesseract >nul 2>&1
if errorlevel 1 (
    echo [WARNING] Tesseract OCR not found - OCR for scanned PDFs unavailable.
    echo Download: https://github.com/UB-Mannheim/tesseract/wiki
)

:: [4/4] Start
echo [4/4] Starting service...
echo.
echo ==========================================
echo   Service ready: http://localhost:8000
echo   Press Ctrl+C to stop
echo ==========================================
echo.
python backend\main.py
pause
