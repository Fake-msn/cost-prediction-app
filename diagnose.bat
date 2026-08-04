@echo off
chcp 65001 >nul
title Project Startup Diagnostic
echo ==========================================
echo   Cost Prediction App - Quick Diagnostic
echo ==========================================
echo.

echo [1] Python
python --version 2>&1
if errorlevel 1 (echo   FAILED - Python not found & goto :fail)
echo   OK

echo [2] venv\Scripts\python.exe
if exist "venv\Scripts\python.exe" (
    venv\Scripts\python.exe --version 2>&1
    echo   OK
) else (
    echo   MISSING - run: python -m venv venv
    goto :fail
)

echo [3] models_cache\*.joblib
set COUNT=0
for %%f in (models_cache\*.joblib) do set /a COUNT+=1
echo   %COUNT% files
if %COUNT% LSS 8 (echo   WARNING: expected 8, got %COUNT%)

echo [4] data\cost_prediction.duckdb
if exist "data\cost_prediction.duckdb" (
    echo   OK (%fileSize% bytes)
) else (
    echo   MISSING - will be recreated from Excel on first start
)

echo [5] Try importing backend.main...
venv\Scripts\python.exe -c "import sys; sys.path.insert(0,'backend'); from ml_models import RealModelFactory; from data_loader import DataLoader; print('   Imports OK')" 2>&1
if errorlevel 1 (
    echo   IMPORT FAILED - check dependencies:
    venv\Scripts\python.exe -m pip list 2>&1 | findstr /i "fastapi uvicorn duckdb xgboost agentscope"
    goto :fail
)

echo [6] Starting server (background, 15s timeout)...
start /b venv\Scripts\python.exe backend\main.py >nul 2>&1
set SVR_PID=%errorlevel%
timeout /t 12 /nobreak >nul
powershell -Command "try { (Invoke-WebRequest 'http://127.0.0.1:8000/api/health' -TimeoutSec 5 -UseBasicParsing).StatusCode } catch { 'FAIL' }" 2>&1
echo.
goto :end

:fail
echo.
echo ==========================================
echo   DIAGNOSIS FAILED - See errors above.
echo   Common fixes:
echo   1. Recreate venv:  rmdir /s /q venv ^&^& python -m venv venv
echo   2. Reinstall deps: venv\Scripts\activate ^&^& python -m pip install -r backend\requirements.txt
echo   3. Reset DuckDB:   del data\cost_prediction.duckdb
echo      (It will be recreated from Excel training data)
echo ==========================================
:end
pause
