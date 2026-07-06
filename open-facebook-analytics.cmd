@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" scripts\open_analytics_dashboard.py
) else (
  python scripts\open_analytics_dashboard.py
)
if errorlevel 1 pause
endlocal
