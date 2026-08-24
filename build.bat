@echo off
setlocal
chcp 65001 >nul

if not exist ".venv\Scripts\python.exe" (
    echo [错误] 请先运行 setup.bat 创建开发环境。
    exit /b 1
)

echo [1/3] 安装构建工具...
".venv\Scripts\python.exe" -m pip install pyinstaller
if errorlevel 1 exit /b 1

echo [2/3] 构建 LinguaSpark 快速启动版...
".venv\Scripts\python.exe" "tools\build_release.py"
if errorlevel 1 exit /b 1

echo [3/3] 完成：dist\LinguaSpark\LinguaSpark.exe
echo 配置和密钥不会被打包，首次运行会保存到用户 AppData。
endlocal
