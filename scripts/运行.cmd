@echo off
rem 优先使用现有环境或 pyenv 当前选中的 Python，兼容没有 py 启动器的电脑。
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" "scripts\管理.py" "%~1"
    exit /b
)
call python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) and sys.maxsize > 2**32 else 1)" >nul 2>&1
if not errorlevel 1 (
    call python "scripts\管理.py" "%~1"
    exit /b
)
py -3.10 -c "import sys; sys.exit(0 if sys.maxsize > 2**32 else 1)" >nul 2>&1
if not errorlevel 1 (
    py -3.10 "scripts\管理.py" "%~1"
    exit /b
)
echo 这份是源码版，需要先安装 64 位 Python 3.10 或更新版本。
echo 如果你只想使用安安，下载免安装版，完整解压后双击“安安.exe”即可。
echo 下载页面：https://github.com/WhereamIneeded/anan/releases
echo 已安装 pyenv 的电脑，请确认它已加入系统 PATH，并选择 Python 3.10.11。
exit /b 1
