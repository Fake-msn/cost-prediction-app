@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion

:: ============================================================
::  deploy-modelscope.bat — 将项目部署到 ModelScope 创空间
::
::  用法:
::    deploy\modelscope\deploy-modelscope.bat [--init] [--force]
::
::  选项:
::    --init    首次初始化：克隆 ModelScope 仓库并配置 git
::    --force   强制推送（覆盖远程内容）
::
::  环境变量:
::    MODELSCOPE_TOKEN   ModelScope 访问令牌（可选，用于 HTTPS 认证）
::    MODELSCOPE_REPO    创空间 git 仓库地址
:: ============================================================

set "SCRIPT_DIR=%~dp0"
set "PROJECT_ROOT=%SCRIPT_DIR%..\.."
set "STAGING_DIR=%PROJECT_ROOT%\.modelscope-deploy"
set "REPO=%MODELSCOPE_REPO%"
if "%REPO%"=="" set "REPO=https://modelscope.cn/studios/little0hope/cost-prediction_Ai.git"

set "FORCE=0"
set "INIT=0"

:parse_args
if "%~1"=="" goto :args_done
if /i "%~1"=="--init"  set "INIT=1" & shift & goto :parse_args
if /i "%~1"=="--force" set "FORCE=1" & shift & goto :parse_args
echo 未知参数: %~1
exit /b 1
:args_done

echo ==========================================
echo   ModelScope 创空间部署工具 (Windows)
echo ==========================================
echo.
echo 项目根目录: %PROJECT_ROOT%
echo 目标仓库:   %REPO%
echo.

:: ── 构建认证 URL ──
set "AUTH_URL=%REPO%"
if defined MODELSCOPE_TOKEN (
    set "AUTH_URL=!REPO:https://=https://oauth2:%MODELSCOPE_TOKEN%@!"
)

:: ── 首次初始化 ──
if "%INIT%"=="0" goto :skip_init

echo [1/3] 初始化 ModelScope 部署目录...

if exist "%STAGING_DIR%" (
    echo   暂存目录已存在: %STAGING_DIR%
    echo   如需重新初始化，请先删除该目录
) else (
    git clone "%AUTH_URL%" "%STAGING_DIR%"
    if errorlevel 1 (
        echo.
        echo   克隆失败！请检查：
        echo   1. 创空间是否已创建: https://modelscope.cn/studios/little0hope/cost-prediction
        echo   2. 访问令牌是否正确（设置 MODELSCOPE_TOKEN 环境变量）
        echo   3. 网络连接是否正常
        exit /b 1
    )
)

echo.
echo [2/3] 配置 git 远程仓库...
cd /d "%STAGING_DIR%"
git remote set-url origin "%AUTH_URL%" 2>nul
if errorlevel 1 git remote add origin "%AUTH_URL%" 2>nul

echo.
echo [3/3] 初始化完成！
echo.
echo 后续部署请运行: deploy\modelscope\deploy-modelscope.bat
exit /b 0

:skip_init

:: ── 常规部署 ──
echo [1/5] 准备暂存目录...

if not exist "%STAGING_DIR%\.git" (
    echo   错误: 未找到已初始化的部署目录
    echo   请先运行: deploy\modelscope\deploy-modelscope.bat --init
    exit /b 1
)

:: 清理暂存目录（保留 .git）
echo [2/5] 同步文件...

:: 删除旧文件（保留 .git）
for /d %%D in ("%STAGING_DIR%\*") do (
    if /i not "%%~nxD"==".git" rd /s /q "%%D"
)
for %%F in ("%STAGING_DIR%\*") do del /q "%%F"

:: 复制必要文件
xcopy /e /i /q /y "%PROJECT_ROOT%\backend"      "%STAGING_DIR%\backend\"
xcopy /e /i /q /y "%PROJECT_ROOT%\frontend"     "%STAGING_DIR%\frontend\"
xcopy /e /i /q /y "%PROJECT_ROOT%\data"         "%STAGING_DIR%\data\"
xcopy /e /i /q /y "%PROJECT_ROOT%\models_cache" "%STAGING_DIR%\models_cache\"

:: 复制 ModelScope 专用文件
copy /y "%SCRIPT_DIR%README.md"          "%STAGING_DIR%\"
copy /y "%SCRIPT_DIR%Dockerfile"         "%STAGING_DIR%\"
copy /y "%SCRIPT_DIR%.dockerignore"      "%STAGING_DIR%\"
copy /y "%SCRIPT_DIR%ms_deploy.json"     "%STAGING_DIR%\"
copy /y "%SCRIPT_DIR%requirements-ms.txt" "%STAGING_DIR%\"

:: 删除 __pycache__ 和 .pyc 文件
for /d /r "%STAGING_DIR%" %%D in ("__pycache__") do (
    if exist "%%D" rd /s /q "%%D"
)
del /s /q "%STAGING_DIR%\*.pyc" 2>nul

:: 创建 .gitignore（不排除 duckdb，已通过 Git LFS 管理）
(
echo __pycache__/
echo *.pyc
echo *.pyo
) > "%STAGING_DIR%\.gitignore"

:: 确保 Git LFS 跟踪 duckdb 文件
cd /d "%STAGING_DIR%"
git lfs track "*.duckdb" 2>nul

echo [3/5] 提交变更...
cd /d "%STAGING_DIR%"
git config user.email "little0hope@modelscope.cn"
git config user.name "little0hope"
git add -A
git status --short

git diff --cached --quiet
if %errorlevel%==0 (
    echo   无变更，跳过提交
) else (
    for /f "tokens=2 delims==" %%I in ('wmic os get localdatetime /value') do set "DT=%%I"
    set "TIMESTAMP=!DT:~0,8!_!DT:~8,6!"
    git commit -m "deploy: sync from github !TIMESTAMP!"
)

echo [4/5] 推送到 ModelScope...
set "PUSH_ARGS="
if "%FORCE%"=="1" set "PUSH_ARGS=--force"

git push origin master %PUSH_ARGS%
if errorlevel 1 (
    echo.
    echo   推送失败！可能的原因：
    echo   1. 访问令牌已过期，请更新 MODELSCOPE_TOKEN
    echo   2. 网络连接问题
    echo   3. 仓库权限不足
    echo.
    echo   如需强制推送: deploy\modelscope\deploy-modelscope.bat --force
    exit /b 1
)

echo.
echo [5/5] 部署完成！
echo.
echo   创空间地址: https://modelscope.cn/studios/little0hope/cost-prediction
echo   构建状态请在创空间页面查看
echo.
echo   注意: DuckDB 数据文件通过 Git LFS 管理
echo   首次推送后如需更新数据，请替换 data/cost_prediction.duckdb 后重新部署
exit /b 0
