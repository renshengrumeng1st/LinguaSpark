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

echo [2/3] 构建 LinguaSpark...
set "DICT_ARG="
if exist "data\ecdict_core.sqlite3" set "DICT_ARG=--add-data data\ecdict_core.sqlite3;data"
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onefile --windowed ^
    --name "LinguaSpark" ^
    --add-data "assets;assets" ^
    %DICT_ARG% ^
    --hidden-import pythoncom ^
    --hidden-import win32com.client ^
    --hidden-import comtypes.client ^
    --hidden-import comtypes.gen.UIAutomationClient ^
    main.py
if errorlevel 1 exit /b 1

echo [3/3] 完成：dist\LinguaSpark.exe
echo 配置和密钥不会被打包，首次运行会保存到用户 AppData。
endlocal
