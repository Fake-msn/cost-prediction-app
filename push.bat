@echo off
chcp 65001 >nul
echo ==========================================
echo   推送到 GitHub（自动检测网络）
echo ==========================================

:: Step 1: 尝试直连推送
echo [1/3] 尝试直连推送...
git push origin main
if %errorlevel% equ 0 (
    echo [3/3] 直连推送成功！
    pause
    exit /b 0
)

:: Step 2: 直连失败，尝试代理推送
echo.
echo [2/3] 直连失败，尝试使用代理推送...
git -c http.proxy=http://127.0.0.1:7890 -c https.proxy=http://127.0.0.1:7890 push origin main
if %errorlevel% equ 0 (
    echo [3/3] 代理推送成功！
    pause
    exit /b 0
)

:: Step 3: 两者都失败
echo.
echo [错误] 直连和代理均推送失败
echo.
echo 建议：
echo   1. 检查网络连接是否正常
echo   2. 确认代理软件已启动（端口7890）
echo   3. 手动直连推送：git push origin main
echo   4. 手动代理推送：git -c http.proxy=http://127.0.0.1:7890 push origin main
echo   5. 或使用 Gitee 镜像推送
pause
exit /b 1
