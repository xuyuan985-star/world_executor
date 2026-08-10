@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title WorldExecutor Launcher

REM ============ 1. Find Python 3.12+ (m7 requires >=3.12 - PEP 701) ============
set "PY_CMD="
py -3.14 --version >nul 2>nul
if not errorlevel 1 set "PY_CMD=py -3.14"
if not defined PY_CMD (
    py -3.13 --version >nul 2>nul
    if not errorlevel 1 set "PY_CMD=py -3.13"
)
if not defined PY_CMD (
    py -3.12 --version >nul 2>nul
    if not errorlevel 1 set "PY_CMD=py -3.12"
)
if not defined PY_CMD (
    python --version >nul 2>nul
    if not errorlevel 1 (
        python -c "import sys;sys.exit(0 if sys.version_info>=(3,12) else 1)" >nul 2>nul
        if not errorlevel 1 set "PY_CMD=python"
    )
)
if not defined PY_CMD (
    echo [ERROR] Python 3.12+ not found.
    echo Please install Python 3.12+ with Add to PATH:
    echo   https://www.python.org/downloads/
    pause
    exit /b 1
)
echo [env] Using Python: %PY_CMD%

REM ============ 2. Bootstrap venv (create + install deps on first run) ============
if exist ".venv\Scripts\python.exe" goto run
echo.
echo [first-run] Creating virtual env...
%PY_CMD% -m venv .venv
if errorlevel 1 (
    echo [ERROR] venv creation failed - check Python installation.
    pause
    exit /b 1
)
echo [first-run] Installing dependencies (1-3 min, please wait)...
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Dependency install failed - check network and retry.
    pause
    exit /b 1
)
echo [done] Dependencies installed.

:run
REM ============ 3. Launch GUI elevated ============
powershell -NoProfile -Command "Start-Process -FilePath '.\.venv\Scripts\pythonw.exe' -ArgumentList '-m','app','--no-elevate' -WorkingDirectory '%~dp0' -Verb RunAs"
echo Launching (confirm UAC prompt)...
exit /b 0
