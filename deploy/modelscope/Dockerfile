FROM python:3.11-slim

WORKDIR /app

# 使用阿里云 Debian 镜像加速（兼容新旧两种 sources 格式）
RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || true; \
    sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list 2>/dev/null || true; \
    apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    tesseract-ocr \
    tesseract-ocr-chi-sim \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件
COPY requirements-ms.txt ./requirements-ms.txt

# 使用阿里云 PyPI 镜像安装 Python 依赖
# xgboost 的 Linux wheel 会拉入 NVIDIA CUDA 包（~2GB），CPU 模式不需要
# 用 --no-deps 安装 xgboost，再单独安装其核心 CPU 依赖（numpy、scipy）
RUN pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ \
    --trusted-host mirrors.aliyun.com \
    "xgboost>=2.0.0" --no-deps && \
    pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ \
    --trusted-host mirrors.aliyun.com \
    "numpy>=1.26.4" "scikit-learn>=1.4.0" && \
    pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ \
    --trusted-host mirrors.aliyun.com \
    -r requirements-ms.txt

# 预装 DuckDB excel 扩展（best-effort）：扩展仓库不在阿里云镜像内，下载失败不阻断构建，
# 运行时 excel_reader 会自动回退 pd.read_excel(openpyxl)。
RUN python -c "import duckdb; duckdb.connect().execute('INSTALL excel; LOAD excel;'); print('excel extension preinstalled')" \
    || echo "WARN: excel extension preinstall skipped; runtime will fall back to pandas/openpyxl"

# 复制应用代码
COPY backend/ ./backend/
COPY frontend/ ./frontend/
COPY data/ ./data/
COPY models_cache/ ./models_cache/

# 创建输出目录
RUN mkdir -p output

# 环境变量
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
ENV PORT=7860
ENV CORS_ORIGINS=https://modelscope.cn,https://*.modelscope.cn,http://localhost:7860

# 暴露端口
EXPOSE 7860

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=60s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:7860/api/health', timeout=5)"

# 启动命令
CMD ["python", "backend/main.py"]
