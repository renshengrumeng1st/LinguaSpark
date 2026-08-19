@echo off
setlocal
chcp 65001 >nul
if not exist ".venv\Scripts\python.exe" (
    echo 请先运行 setup.bat
    exit /b 1
)
".venv\Scripts\python.exe" main.py
endlocal
