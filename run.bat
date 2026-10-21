@echo off
rem Windows: one command -> deps, data, build, dashboard. The real work is in run.py.
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 run.py %*
) else (
  where python >nul 2>nul
  if errorlevel 1 (
    echo Python 3.10+ not found. Install it from python.org ^(tick "Add python.exe to PATH"^) and rerun.
    exit /b 1
  )
  python run.py %*
)
