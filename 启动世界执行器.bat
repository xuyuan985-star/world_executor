@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 世界执行器 WorldExecutor
echo 正在启动世界执行器...
".venv\Scripts\python.exe" -m app
if errorlevel 1 (
    echo.
    echo 启动失败，按任意键关闭...
    pause >nul
)
