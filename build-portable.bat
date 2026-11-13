@echo off
setlocal
cd /d "%~dp0"

set "PY=%~dp0.venv\Scripts\python.exe"
set "DIST="
set "PIP_MIRROR=https://pypi.tuna.tsinghua.edu.cn/simple"
set "NPM_MIRROR=https://registry.npmmirror.com"

echo ============================================
echo   WeChat Exporter - Portable Build
echo ============================================
echo.

rem ---------- 1. Python virtual environment ----------
if not exist "%PY%" (
  echo [1/5] Creating virtual environment...
  python -m venv .venv
  if errorlevel 1 goto :fail
) else (
  echo [1/5] Python virtual environment found
)

echo       Installing / checking Python dependencies...
"%PY%" -m pip install -q -r requirements.txt -i %PIP_MIRROR%
if errorlevel 1 goto :fail

"%PY%" -c "import PyInstaller" >nul 2>nul
if errorlevel 1 (
  echo       Installing PyInstaller...
  "%PY%" -m pip install -q pyinstaller -i %PIP_MIRROR%
  if errorlevel 1 goto :fail
)

rem ---------- 2. Build frontend ----------
echo [2/5] Building frontend...
where npm >nul 2>nul
if errorlevel 1 (
  if not exist "webui\dist\index.html" (
    echo [ERROR] Node.js not found and webui\dist is missing. Cannot build.
    goto :fail
  )
  echo [WARN] npm not found, using existing webui\dist
) else (
  pushd webui
  if not exist "node_modules" (
    echo       Installing frontend dependencies...
    call npm install --registry=%NPM_MIRROR%
    if errorlevel 1 (
      popd
      goto :fail
    )
  )
  call npm run build
  if errorlevel 1 (
    popd
    goto :fail
  )
  popd
)

rem ---------- 3. Clean old output ----------
echo [3/5] Cleaning old build output...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

rem ---------- 4. PyInstaller ----------
echo [4/5] Packaging (about 3-10 minutes)...
"%PY%" -m PyInstaller packaging\app.spec --noconfirm --clean
if errorlevel 1 goto :fail

rem ---------- 5. Extra files ----------
echo [5/5] Copying usage and license files...
for /d %%D in ("dist\*") do set "DIST=%%~fD"
if not defined DIST goto :fail
copy /Y "docs\USAGE.md" "%DIST%\USAGE.md" >nul
copy /Y "LICENSE" "%DIST%\LICENSE.txt" >nul
copy /Y "NOTICE.md" "%DIST%\NOTICE.md" >nul

echo.
echo ============================================
echo   Build complete
echo   Output: %DIST%
echo.
echo   Copy the whole folder above to another PC and
echo   double-click the exe to run.
echo   Target: Windows 10/11 with WebView2 runtime.
echo   FFmpeg is optional (image / video processing).
echo ============================================
echo.

if not defined NO_OPEN if exist "%DIST%" explorer "%DIST%"
if not defined NO_PAUSE pause
exit /b 0

:fail
echo.
echo [FAILED] Build did not finish. Check the messages above.
echo.
if not defined NO_PAUSE pause
exit /b 1
