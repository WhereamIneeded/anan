@echo off
setlocal
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
call scripts\运行.cmd build
if errorlevel 1 (
    pause
    exit /b 1
)
