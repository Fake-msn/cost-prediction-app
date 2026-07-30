#!/bin/bash
echo "=========================================="
echo "  工程造价预测AI系统 - 一键启动"
echo "=========================================="

if ! command -v python3 &> /dev/null; then
    echo "[错误] 未找到 Python3，请先安装 Python 3.11+"
    exit 1
fi

if [ ! -d "venv" ]; then
    echo "[1/4] 创建虚拟环境..."
    python3 -m venv venv
fi

echo "[2/4] 激活虚拟环境..."
source venv/bin/activate

echo "[3/4] 安装/更新依赖..."
pip install -r backend/requirements.txt -q

if ! command -v tesseract &> /dev/null; then
    echo "[警告] 未找到 Tesseract OCR"
    echo "  Ubuntu/Debian: sudo apt-get install tesseract-ocr tesseract-ocr-chi-sim"
    echo "  macOS: brew install tesseract tesseract-lang"
fi

echo "[4/4] 启动服务..."
echo ""
echo "=========================================="
echo "  服务已启动: http://localhost:8000"
echo "  按 Ctrl+C 停止服务"
echo "=========================================="
echo ""
python backend/main.py
