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
  echo [1/6] Creating virtual environment...
  python -m venv .venv
  if errorlevel 1 goto :fail
) else (
  echo [1/6] Python virtual environment found
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
echo [2/6] Building frontend...
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

rem ---------- 3. Bundle FFmpeg ----------
echo [3/6] Preparing bundled FFmpeg...
if exist "packaging\ffmpeg\ffmpeg.exe" (
  echo       Bundled FFmpeg already staged
) else (
  set "FFSRC="
  where ffmpeg > "%TEMP%\wce_ff.txt" 2>nul
  for /f "delims=" %%P in ('type "%TEMP%\wce_ff.txt" 2^>nul') do if not defined FFSRC set "FFSRC=%%~dpP"
  del "%TEMP%\wce_ff.txt" >nul 2>nul
  if defined FFSRC (
    echo       Bundling FFmpeg from "%FFSRC%"
    if not exist "packaging\ffmpeg" mkdir "packaging\ffmpeg"
    copy /Y "%FFSRC%ffmpeg.exe" "packaging\ffmpeg\" >nul
    if exist "%FFSRC%ffprobe.exe" copy /Y "%FFSRC%ffprobe.exe" "packaging\ffmpeg\" >nul
    if exist "%FFSRC%..\LICENSE" copy /Y "%FFSRC%..\LICENSE" "packaging\ffmpeg\LICENSE.txt" >nul
    if exist "packaging\ffmpeg\LICENSE.txt" if not exist "packaging\licenses\GPLv3.txt" copy /Y "packaging\ffmpeg\LICENSE.txt" "packaging\licenses\GPLv3.txt" >nul
  ) else (
    echo [WARN] ffmpeg not found in PATH; the package will NOT include FFmpeg.
    echo        Put ffmpeg.exe / ffprobe.exe into packaging\ffmpeg and rebuild.
  )
)

rem ---------- 4. Backup runtime data, then clean ----------
echo [4/6] Backing up runtime data and cleaning old output...
set "BACKUP=%~dp0dist_runtime_backup"
if exist "%BACKUP%" (
  echo [WARN] Keeping existing runtime backup: %BACKUP%
) else (
  if exist "dist\WeChatExporter" (
    mkdir "%BACKUP%"
    for %%D in (data media exports) do (
      if exist "dist\WeChatExporter\%%D" move "dist\WeChatExporter\%%D" "%BACKUP%\%%D" >nul
    )
  )
)
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist dist (
  echo [ERROR] dist folder is in use. Close the running app and run this script again.
  goto :fail
)

rem ---------- 5. PyInstaller ----------
echo [5/6] Packaging (about 3-10 minutes)...
"%PY%" -m PyInstaller packaging\app.spec --noconfirm --clean
if errorlevel 1 goto :fail

rem ---------- 6. Extra files ----------
echo [6/6] Copying usage and license files...
for /d %%D in ("dist\*") do set "DIST=%%~fD"
if not defined DIST goto :fail

rem ---------- restore runtime data ----------
if exist "%BACKUP%" (
  for %%D in (data media exports) do (
    if exist "%BACKUP%\%%D" move "%BACKUP%\%%D" "%DIST%\%%D" >nul
  )
  rmdir /s /q "%BACKUP%" 2>nul
)
rem Release package must not ship a machine-specific config.json
if exist "%DIST%\config.json" del /q "%DIST%\config.json"

copy /Y "docs\USAGE.md" "%DIST%\USAGE.md" >nul
copy /Y "LICENSE" "%DIST%\LICENSE.txt" >nul
copy /Y "NOTICE.md" "%DIST%\NOTICE.md" >nul

rem ---------- third-party licenses ----------
if exist "packaging\licenses" (
  echo       Copying third-party licenses...
  mkdir "%DIST%\licenses" >nul 2>nul
  copy /Y "packaging\licenses\*" "%DIST%\licenses\" >nul
)

echo.
echo ============================================
echo   Build complete
echo   Output: %DIST%
echo.
echo   Copy the whole folder above to another PC and
echo   double-click the exe to run.
echo   Target: Windows 10/11 with WebView2 runtime.
echo   FFmpeg is bundled in _internal\ffmpeg (auto-added to PATH at startup).
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
