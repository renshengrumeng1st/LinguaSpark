@echo off
setlocal
chcp 65001 >nul

if not exist ".venv\Scripts\python.exe" python -m venv .venv
if errorlevel 1 exit /b 1

".venv\Scripts\python.exe" -m pip install -r requirements-dev.txt
if errorlevel 1 exit /b 1

echo 环境准备完成。运行 run.bat 启动，运行 test.bat 测试。
endlocal
