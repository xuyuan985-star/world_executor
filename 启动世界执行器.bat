@echo off
chcp 65001 >nul
cd /d "%~dp0"
powershell -NoProfile -Command "Start-Process -FilePath '.\\.venv\\Scripts\\pythonw.exe' -ArgumentList '-m','app','--no-elevate' -WorkingDirectory '%~dp0' -Verb RunAs"
