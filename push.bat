@echo off
chcp 65001 >nul
echo ==========================================
echo   Push to GitHub (auto proxy fallback)
echo ==========================================

:: Tag to push (usage: push.bat [tag], default v1.8.0)
set "TAG=v1.8.0"
if not "%1"=="" set "TAG=%1"

echo [1/4] Pushing main branch...
git push origin main
if errorlevel 1 goto :probe_proxy

echo [2/4] Pushing tag %TAG% (force update)...
git push origin %TAG% --force
if errorlevel 1 goto :probe_proxy

echo.
echo [4/4] Push OK! main + %TAG%
goto :done

:probe_proxy
echo.
echo [2/4] Direct push failed. Probing running proxy ports...
set "PROXY="
for %%p in (7890 7897 10809 10808 1080 2080 8080 8888) do (
    curl.exe -sS -o NUL --connect-timeout 3 -x http://127.0.0.1:%%p https://api.github.com 2>nul
    if not errorlevel 1 (
        set "PROXY=http://127.0.0.1:%%p"
        goto :proxy_found
    )
)
echo [3/4] No running proxy detected. See manual steps below.
goto :manual_hint

:proxy_found
echo [3/4] Proxy found: %PROXY%
git -c http.proxy=%PROXY% -c https.proxy=%PROXY% push origin main
if errorlevel 1 goto :manual_hint
git -c http.proxy=%PROXY% -c https.proxy=%PROXY% push origin %TAG% --force
if errorlevel 1 goto :manual_hint
echo [4/4] Proxy push OK! main + %TAG%
goto :done

:manual_hint
echo.
echo ==========================================
echo   [ERROR] Push failed. Possible causes:
echo   1. Direct connection to github.com is blocked
echo      (DNS resolves to an unreachable IP)
echo   2. Proxy software is NOT running
echo.
echo   FIX: start your proxy tool (Clash / v2rayN /
echo   Shadowsocks etc), then re-run this script.
echo.
echo   Manual commands:
echo     git push origin main
echo     git push origin %TAG% --force
echo.
echo   Gitee mirror fallback: setup-gitee-mirror.bat
echo ==========================================
:done
pause
