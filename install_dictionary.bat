@echo off
setlocal
chcp 65001 >nul
if "%~1"=="" (
    echo 用法：install_dictionary.bat ECDICT_CSV文件路径
    echo 下载 ecdict.csv 后，将文件拖到此脚本上即可生成本地词典。
    exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
    echo 请先运行 setup.bat
    exit /b 1
)
".venv\Scripts\python.exe" tools\build_dictionary.py "%~1" "data\ecdict_core.sqlite3"
if errorlevel 1 exit /b 1
echo 本地词典生成完成：data\ecdict_core.sqlite3
endlocal
