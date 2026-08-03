@echo off
echo ==========================================
echo   Setup Gitee mirror (domestic push backup)
echo ==========================================
echo.
echo This script adds Gitee as an alternate push remote.
echo Please create the same-named repo on gitee.com first.
echo.
set /p GITEE_URL=Enter Gitee repo URL (e.g. https://gitee.com/xxx/cost-prediction-app.git): 

git remote add gitee %GITEE_URL%
echo.
echo Gitee remote added: %GITEE_URL%
echo Push with: git push gitee main
pause
