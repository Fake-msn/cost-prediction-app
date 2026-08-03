#!/bin/bash
set -e

echo "=========================================="
echo "  工程造价预测AI系统 - 一键启动"
echo "=========================================="

# ============================================================
# [1/4] Python 3.11+ Detection & Auto-Installation
# ============================================================
echo "[1/4] 检查 Python 3.11+ 环境..."

PY_CMD=""
ensure_python() {
    local cmd="$1"
    if command -v "$cmd" &> /dev/null; then
        if "$cmd" -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)" 2>/dev/null; then
            PY_CMD="$cmd"
            return 0
        fi
    fi
    return 1
}

# Try python3 and python
if ensure_python "python3"; then true
elif ensure_python "python"; then true
else
    # ---- Auto-Install Python 3.11+ ----
    echo "[1/4] 未检测到 Python 3.11+，尝试自动安装..."

    OS="$(uname -s)"
    case "$OS" in
        Darwin)
            # macOS: try Homebrew
            if command -v brew &> /dev/null; then
                echo "[1/4] 通过 Homebrew 安装 python@3.11..."
                brew install python@3.11 2>/dev/null || true
                # Link & add to PATH
                if [ -f "$(brew --prefix 2>/dev/null)/opt/python@3.11/bin/python3.11" ]; then
                    export PATH="$(brew --prefix)/opt/python@3.11/bin:$PATH"
                elif [ -f "/opt/homebrew/opt/python@3.11/bin/python3.11" ]; then
                    export PATH="/opt/homebrew/opt/python@3.11/bin:$PATH"
                elif [ -f "/usr/local/opt/python@3.11/bin/python3.11" ]; then
                    export PATH="/usr/local/opt/python@3.11/bin:$PATH"
                fi
                ensure_python "python3.11" || ensure_python "python3" || ensure_python "python"
            fi
            if [ -z "$PY_CMD" ]; then
                echo "[提示] macOS 自动安装失败。"
                echo "  方案1: 安装 Homebrew 后重试:  /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
                echo "  方案2: 官方安装包:  https://www.python.org/downloads/"
                exit 1
            fi
            ;;
        Linux)
            # Detect distro and use appropriate package manager
            if command -v apt-get &> /dev/null; then
                echo "[1/4] 通过 apt 安装 python3.11..."
                sudo apt-get update -qq
                sudo apt-get install -y -qq python3.11 python3.11-venv python3.11-dev 2>/dev/null || true
                ensure_python "python3.11" || ensure_python "python3"
            elif command -v dnf &> /dev/null; then
                echo "[1/4] 通过 dnf 安装 python3.11..."
                sudo dnf install -y python3.11 python3.11-devel 2>/dev/null || true
                ensure_python "python3.11" || ensure_python "python3"
            elif command -v yum &> /dev/null; then
                echo "[1/4] 通过 yum 安装 python3.11..."
                sudo yum install -y python3.11 python3.11-devel 2>/dev/null || true
                ensure_python "python3.11" || ensure_python "python3"
            elif command -v zypper &> /dev/null; then
                echo "[1/4] 通过 zypper 安装 python3.11..."
                sudo zypper install -y python311 python311-devel 2>/dev/null || true
                ensure_python "python3.11" || ensure_python "python3"
            else
                echo "[1/4] 未知 Linux 发行版，无法自动安装。"
            fi
            if [ -z "$PY_CMD" ]; then
                echo "[错误] Linux 自动安装失败。请手动安装 Python 3.11+:"
                echo "  Ubuntu/Debian:  sudo apt-get install python3.11 python3.11-venv"
                echo "  RHEL/CentOS:    sudo dnf install python3.11"
                echo "  openSUSE:       sudo zypper install python311"
                exit 1
            fi
            ;;
        *)
            echo "[错误] 不支持的操作系统: $OS"
            echo "请手动安装 Python 3.11+: https://www.python.org/downloads/"
            exit 1
            ;;
    esac
fi

echo "[1/4] Python $($PY_CMD --version 2>&1) ready  [命令: $PY_CMD]"

# ---- Create venv if missing ----
if [ ! -d "venv" ]; then
    echo "[1/4] 创建虚拟环境..."
    $PY_CMD -m venv venv
fi

# [2/4] Activate venv
echo "[2/4] 激活虚拟环境..."
source venv/bin/activate

# [3/4] Install dependencies
echo "[3/4] 安装/更新依赖..."
pip install -r backend/requirements.txt -q

# ---- Pre-flight checks ----

# Model files (models_cache/*.joblib)
if ! ls models_cache/*.joblib >/dev/null 2>&1; then
    echo "[错误] 未找到预训练模型文件 (models_cache/*.joblib)"
    echo "请确保完整下载了项目文件，或重新 clone 仓库"
    exit 1
fi

# Tesseract OCR + Chinese language pack
if command -v tesseract &> /dev/null; then
    if tesseract --list-langs 2>/dev/null | grep -q chi_sim; then
        echo "[OK] Tesseract OCR (含中文语言包) 已就绪"
    else
        echo "[警告] Tesseract 已安装但缺少中文语言包 (chi_sim)"
        echo "  Ubuntu/Debian: sudo apt-get install tesseract-ocr-chi-sim"
        echo "  macOS:         brew install tesseract-lang"
        echo "  扫描件 OCR 将无法正常工作"
    fi
else
    echo "[警告] 未找到 Tesseract OCR - 扫描件 OCR 不可用"
    echo "  Ubuntu/Debian: sudo apt-get install tesseract-ocr tesseract-ocr-chi-sim"
    echo "  macOS:         brew install tesseract tesseract-lang"
fi

# [4/4] Start service
echo "[4/4] 启动服务..."
echo ""
echo "=========================================="
echo "  服务已启动: http://localhost:8000"
echo "  按 Ctrl+C 停止服务"
echo "=========================================="
echo ""
echo "[提示] 如需 AI 对话功能，请复制 .env.example 为 .env 并填入 API Key"
echo ""
$PY_CMD backend/main.py
