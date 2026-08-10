@echo off
chcp 65001 >nul
cd /d "%~dp0"
title WorldExecutor 启动器

REM ============ 1. 找 Python 3.12+（m7 官方要求 >=3.12——PEP 701） ============
set "PY_CMD="
for %%V in (3.14 3.13 3.12) do (
    if not defined PY_CMD (
        py -%%V --version >nul 2>nul && set "PY_CMD=py -%%V"
    )
)
if not defined PY_CMD (
    python --version >nul 2>nul
    if not errorlevel 1 (
        python -c "import sys; sys.exit(0 if sys.version_info>=(3,12) else 1)" >nul 2>nul
        if not errorlevel 1 set "PY_CMD=python"
    )
)
if not defined PY_CMD (
    echo [错误] 未找到 Python 3.12+。
    echo 请安装 Python 3.12 或更高版本（勾选 Add to PATH）：
    echo   https://www.python.org/downloads/
    pause
    exit /b 1
)
echo [环境] 使用 Python：%PY_CMD%

REM ============ 2. 自举虚拟环境（首次自动创建 + 装依赖） ============
if not exist ".venv\Scripts\python.exe" (
    echo.
    echo [首次启动] 创建虚拟环境...
    %PY_CMD% -m venv .venv
    if errorlevel 1 (
        echo [错误] 虚拟环境创建失败——请检查 Python 安装
        pause
        exit /b 1
    )
    echo [首次启动] 安装依赖（约 1-3 分钟，请耐心等待）...
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [错误] 依赖安装失败——请检查网络后重试
        pause
        exit /b 1
    )
    echo [完成] 依赖安装完成
)

REM ============ 3. 提权启动 GUI ============
powershell -NoProfile -Command "Start-Process -FilePath '.\.venv\Scripts\pythonw.exe' -ArgumentList '-m','app','--no-elevate' -WorkingDirectory '%~dp0' -Verb RunAs"

echo 启动中（管理员权限确认后窗口出现）...
exit /b 0
