@echo off
setlocal
chcp 65001 >nul
set "PSModulePath=%SystemRoot%\System32\WindowsPowerShell\v1.0\Modules"
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\下载并启动.ps1"
if errorlevel 1 (
    echo 下载或启动失败，请阅读上方中文说明。
    pause
    exit /b 1
)
exit /b 0
