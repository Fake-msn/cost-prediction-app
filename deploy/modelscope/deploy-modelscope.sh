#!/usr/bin/env bash
#
# deploy-modelscope.sh — 将项目部署到 ModelScope 创空间
#
# 用法:
#   bash deploy/modelscope/deploy-modelscope.sh [--init] [--force]
#
# 选项:
#   --init    首次初始化：克隆 ModelScope 仓库并配置 git
#   --force   强制推送（覆盖远程内容）
#
# 前置条件:
#   1. 已在 ModelScope 创建创空间并获取 git 访问令牌
#   2. git 已配置用户信息 (user.name / user.email)
#
# 环境变量:
#   MODELSCOPE_TOKEN   ModelScope 访问令牌（可选，用于 HTTPS 认证）
#   MODELSCOPE_REPO    创空间 git 仓库地址
#                      默认: https://modelscope.cn/studios/little0hope/cost-prediction.git

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
STAGING_DIR="$PROJECT_ROOT/.modelscope-deploy"

REPO="${MODELSCOPE_REPO:-https://modelscope.cn/studios/little0hope/cost-prediction_Ai.git}"
FORCE=false
INIT=false

for arg in "$@"; do
    case "$arg" in
        --init)  INIT=true ;;
        --force) FORCE=true ;;
        *)       echo "未知参数: $arg"; exit 1 ;;
    esac
done

echo "=========================================="
echo "  ModelScope 创空间部署工具"
echo "=========================================="
echo ""
echo "项目根目录: $PROJECT_ROOT"
echo "目标仓库:   $REPO"
echo ""

# ── 构建认证 URL ──
build_auth_url() {
    if [ -n "${MODELSCOPE_TOKEN:-}" ]; then
        echo "$REPO" | sed "s|https://|https://oauth2:${MODELSCOPE_TOKEN}@|"
    else
        echo "$REPO"
    fi
}

# ── 首次初始化 ──
if $INIT; then
    echo "[1/3] 初始化 ModelScope 部署目录..."

    if [ -d "$STAGING_DIR" ]; then
        echo "  暂存目录已存在: $STAGING_DIR"
        echo "  如需重新初始化，请先删除该目录"
    else
        AUTH_URL=$(build_auth_url)
        git clone "$AUTH_URL" "$STAGING_DIR" || {
            echo ""
            echo "  克隆失败！请检查："
            echo "  1. 创空间是否已创建: https://modelscope.cn/studios/little0hope/cost-prediction"
            echo "  2. 访问令牌是否正确（设置 MODELSCOPE_TOKEN 环境变量）"
            echo "  3. 网络连接是否正常"
            exit 1
        }
    fi

    echo ""
    echo "[2/3] 配置 git 远程仓库..."
    cd "$STAGING_DIR"
    git remote set-url origin "$(build_auth_url)" 2>/dev/null || \
    git remote add origin "$(build_auth_url)" 2>/dev/null || true

    echo ""
    echo "[3/3] 初始化完成！"
    echo ""
    echo "后续部署请运行: bash deploy/modelscope/deploy-modelscope.sh"
    exit 0
fi

# ── 常规部署 ──
echo "[1/5] 准备暂存目录..."

if [ ! -d "$STAGING_DIR/.git" ]; then
    echo "  错误: 未找到已初始化的部署目录"
    echo "  请先运行: bash deploy/modelscope/deploy-modelscope.sh --init"
    exit 1
fi

# 清理暂存目录（保留 .git）
echo "[2/5] 同步文件..."
find "$STAGING_DIR" -mindepth 1 -maxdepth 1 ! -name '.git' -exec rm -rf {} +

# 复制必要文件
cp -r "$PROJECT_ROOT/backend"      "$STAGING_DIR/"
cp -r "$PROJECT_ROOT/frontend"     "$STAGING_DIR/"
cp -r "$PROJECT_ROOT/data"         "$STAGING_DIR/"
cp -r "$PROJECT_ROOT/models_cache" "$STAGING_DIR/"

# 复制 ModelScope 专用文件
cp "$SCRIPT_DIR/README.md"          "$STAGING_DIR/"
cp "$SCRIPT_DIR/Dockerfile"         "$STAGING_DIR/"
cp "$SCRIPT_DIR/.dockerignore"      "$STAGING_DIR/"
cp "$SCRIPT_DIR/ms_deploy.json"     "$STAGING_DIR/"
cp "$SCRIPT_DIR/requirements-ms.txt" "$STAGING_DIR/"

# 删除 __pycache__ 和 .pyc 文件
find "$STAGING_DIR" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find "$STAGING_DIR" -name "*.pyc" -delete 2>/dev/null || true

# 创建 .gitignore 排除不需要的文件（不排除 duckdb，已通过 Git LFS 管理）
cat > "$STAGING_DIR/.gitignore" << 'GITIGNORE'
__pycache__/
*.pyc
*.pyo
.history.json
.sessions.json
.projects.json
GITIGNORE

# 确保 Git LFS 跟踪 duckdb 文件
cd "$STAGING_DIR"
git lfs track "*.duckdb" 2>/dev/null || true

echo "[3/5] 提交变更..."
cd "$STAGING_DIR"
git config user.email "little0hope@modelscope.cn"
git config user.name "little0hope"
git add -A
git status --short

if git diff --cached --quiet; then
    echo "  无变更，跳过提交"
else
    TIMESTAMP=$(date +%Y%m%d_%H%M%S)
    git commit -m "deploy: sync from github $TIMESTAMP"
fi

echo "[4/5] 推送到 ModelScope..."
PUSH_ARGS=""
if $FORCE; then
    PUSH_ARGS="--force"
fi

git push origin master $PUSH_ARGS || {
    echo ""
    echo "  推送失败！可能的原因："
    echo "  1. 访问令牌已过期，请更新 MODELSCOPE_TOKEN"
    echo "  2. 网络连接问题"
    echo "  3. 仓库权限不足"
    echo ""
    echo "  如需强制推送: bash deploy/modelscope/deploy-modelscope.sh --force"
    exit 1
}

echo ""
echo "[5/5] 部署完成！"
echo ""
echo "  创空间地址: https://modelscope.cn/studios/little0hope/cost-prediction"
echo "  构建状态请在创空间页面查看"
echo ""
echo "  注意: DuckDB 数据文件通过 Git LFS 管理"
echo "  首次推送后如需更新数据，请替换 data/cost_prediction.duckdb 后重新部署"
