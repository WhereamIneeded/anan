@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist .venv\Scripts\pythonw.exe (
    echo 首次开发请先运行 构建.cmd，或下载 GitHub 成品。
    pause
    exit /b 1
)
start "" .venv\Scripts\pythonw.exe -m anan_pet
