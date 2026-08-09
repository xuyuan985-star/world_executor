@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 世界执行器 WorldExecutor
rem 用 pythonw.exe 启动——无控制台黑窗；日志走文件（logs/），错误弹窗提示
".venv\Scripts\pythonw.exe" -m app
if errorlevel 1 (
    echo.
    echo 启动失败，按任意键关闭...
    pause >nul
)
