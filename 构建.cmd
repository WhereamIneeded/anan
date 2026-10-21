@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
    py -3.10 -m venv .venv
    if errorlevel 1 (
        echo 请先安装 Windows x64 Python 3.10，或从 GitHub 下载已经构建的成品。
        pause
        exit /b 1
    )
)
.venv\Scripts\python.exe -m pip install -r requirements.lock
if errorlevel 1 goto :失败
.venv\Scripts\python.exe -m pip install --no-deps --no-build-isolation -e .
if errorlevel 1 goto :失败
.venv\Scripts\python.exe -m pytest -q
if errorlevel 1 goto :失败
.venv\Scripts\python.exe scripts\构建.py
if errorlevel 1 goto :失败
echo 构建完成，请查看 dist 目录。
pause
exit /b 0
:失败
echo 构建未完成，请查看上方错误信息。
pause
exit /b 1
