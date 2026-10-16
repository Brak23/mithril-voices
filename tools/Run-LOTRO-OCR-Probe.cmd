@echo off
setlocal
cd /d "%~dp0.." || exit /b 1
if not exist ".venv\Scripts\python.exe" (
  echo The task Python environment is missing.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -u -m lvc.platform.windows.lotro_user_probe
echo.
echo Probe finished. This window will stay open until you press a key.
pause
