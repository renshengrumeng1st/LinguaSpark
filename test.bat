@echo off
setlocal
chcp 65001 >nul
set "PYTHONPATH=%CD%"
set "QT_QPA_PLATFORM=offscreen"
".venv\Scripts\python.exe" -m pytest -q
endlocal
