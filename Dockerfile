FROM python:3.11-slim

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    tesseract-ocr \
    tesseract-ocr-chi-sim \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件
COPY backend/requirements.txt ./backend/requirements.txt

# 安装Python依赖
RUN pip install --no-cache-dir -r backend/requirements.txt

# 预装 DuckDB excel 扩展（构建期联网下载，烘进镜像，运行期离线 LOAD 即可）。
# best-effort：下载失败不阻断构建，运行时 excel_reader 会自动回退 pd.read_excel。
RUN python -c "import duckdb; duckdb.connect().execute('INSTALL excel; LOAD excel;'); print('excel extension preinstalled')" \
    || echo "WARN: excel extension preinstall skipped; runtime will fall back to pandas/openpyxl"

# 复制应用代码
COPY backend/ ./backend/
COPY frontend/ ./frontend/
COPY data/ ./data/

# 创建模型缓存目录
RUN mkdir -p models_cache

# 环境变量
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# 暴露端口
EXPOSE 8000

# 启动命令
CMD ["python", "backend/main.py"]
