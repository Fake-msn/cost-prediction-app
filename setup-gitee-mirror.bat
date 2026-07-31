@echo off
chcp 65001 >nul
echo ==========================================
echo   设置 Gitee 镜像仓库（国内推送备选）
echo ==========================================
echo.
echo 此脚本将添加 Gitee 作为备选推送远程仓库
echo 请先在 gitee.com 创建同名仓库
echo.
set /p GITEE_URL=请输入 Gitee 仓库地址（如 https://gitee.com/xxx/cost-prediction-app.git）:

git remote add gitee %GITEE_URL%
echo.
echo Gitee 远程仓库已添加: %GITEE_URL%
echo 推送命令: git push gitee main
pause
