@echo off
setlocal
cd /d "%~dp0.." || exit /b 2
if not exist ".venv\Scripts\python.exe" (
  echo Mithril task Python is unavailable.
  exit /b 2
)
".venv\Scripts\python.exe" -u -m lvc.platform.windows.lotro_observation_ui %*
exit /b %ERRORLEVEL%
