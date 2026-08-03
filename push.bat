@echo off
echo ==========================================
echo   Push to GitHub (auto proxy fallback)
echo ==========================================

:: Step 1: Try direct push
echo [1/3] Trying direct push...
git push origin main
if %errorlevel% equ 0 (
    echo [3/3] Direct push OK!
    pause
    exit /b 0
)

:: Step 2: Direct failed, try proxy push
echo.
echo [2/3] Direct push failed, trying proxy 127.0.0.1:7890...
git -c http.proxy=http://127.0.0.1:7890 -c https.proxy=http://127.0.0.1:7890 push origin main
if %errorlevel% equ 0 (
    echo [3/3] Proxy push OK!
    pause
    exit /b 0
)

:: Step 3: Both failed
echo.
echo [ERROR] Both direct and proxy push failed.
echo.
echo Suggestions:
echo   1. Check network connectivity
echo   2. Make sure proxy is running on port 7890
echo   3. Push manually: git push origin main
echo   4. Push via proxy: git -c http.proxy=http://127.0.0.1:7890 push origin main
echo   5. Or use Gitee mirror: setup-gitee-mirror.bat
pause
exit /b 1
