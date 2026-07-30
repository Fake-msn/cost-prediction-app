@echo off
chcp 65001 >nul
echo ==========================================
echo   工程造价预测AI系统 - 一键启动
echo ==========================================

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Python，请先安装 Python 3.11+
    echo 下载地址: https://www.python.org/downloads/
    pause
    exit /b 1
)

:: Create venv if not exists
if not exist "venv\Scripts\activate.bat" (
    echo [1/4] 创建虚拟环境...
    python -m venv venv
)

:: Activate
echo [2/4] 激活虚拟环境...
call venv\Scripts\activate.bat

:: Install deps
echo [3/4] 安装/更新依赖...
pip install -r backend\requirements.txt -q

:: Check Tesseract
where tesseract >nul 2>&1
if errorlevel 1 (
    echo [警告] 未找到 Tesseract OCR，PDF扫描件OCR功能不可用
    echo 下载地址: https://github.com/UB-Mannheim/tesseract/wiki
)

:: Start
echo [4/4] 启动服务...
echo.
echo ==========================================
echo   服务已启动: http://localhost:8000
echo   按 Ctrl+C 停止服务
echo ==========================================
echo.
python backend\main.py
