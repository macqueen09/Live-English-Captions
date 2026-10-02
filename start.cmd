@echo off
cd /d "%~dp0"
powershell -NoProfile -Command "try { $s = Invoke-RestMethod 'http://127.0.0.1:8765/api/state' -TimeoutSec 2; if ($null -ne $s.rows) { exit 0 }; exit 1 } catch { exit 1 }"
if not errorlevel 1 (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0launch.ps1"
  exit /b 0
)
findstr /x /c:"1.2.0" "models\.ready" >nul 2>nul
if errorlevel 1 goto install
if not exist "models\whisper-small.en\model.bin" goto install
goto launch
:install
echo Installing Python, dependencies and models...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
if errorlevel 1 (
  pause
  exit /b 1
)
:launch
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0launch.ps1"
if errorlevel 1 pause
