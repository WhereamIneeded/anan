"""自动准备源码运行环境，让日常启动只需双击。"""

import hashlib
import os
import subprocess
import sys
import traceback
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def environment_signature(root):
    digest = hashlib.sha256()
    for name in ("requirements.lock", "pyproject.toml"):
        digest.update((root / name).read_bytes())
    return digest.hexdigest()


def run_checked(command, root, log):
    subprocess.run(command, cwd=root, stdout=log, stderr=subprocess.STDOUT, check=True)


def prepare_environment(root, log):
    python = root / ".venv/Scripts/python.exe"
    if not python.exists():
        print("正在准备安安的运行环境，首次使用请稍候……", flush=True)
        run_checked([sys.executable, "-m", "venv", str(root / ".venv")], root, log)
    marker = root / ".venv/安安依赖.sha256"
    signature = environment_signature(root)
    check = [str(python), "-c", "from PySide6.QtWidgets import QApplication; from PIL import Image; import anan_pet"]
    if marker.exists() and marker.read_text(encoding="utf-8") == signature:
        try:
            run_checked(check, root, log)
            return python
        except subprocess.CalledProcessError:
            pass
    # 先撤销旧标记，安装失败后下次双击会重试。
    marker.unlink(missing_ok=True)
    print("正在准备所需组件，首次使用或版本更新时需要联网……", flush=True)
    run_checked([str(python), "-m", "pip", "install", "-r", "requirements.lock"], root, log)
    run_checked([str(python), "-m", "pip", "install", "--no-deps", "--no-build-isolation", "-e", "."], root, log)
    run_checked(check, root, log)
    marker.write_text(signature, encoding="utf-8")
    return python


def launch(python, root):
    log_path = root / "build/启动日志.txt"
    with log_path.open("a", encoding="utf-8") as log:
        process = subprocess.Popen(
            [str(python.with_name("pythonw.exe")), "-m", "anan_pet"],
            cwd=root, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
        )
    try:
        code = process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        print("安安已打开。右键点击安安可以调整大小或退出。", flush=True)
        return
    raise RuntimeError(f"安安未能持续运行（退出代码 {code}）。请查看 {log_path}")


def main():
    if sys.platform != "win32":
        print("请在 Windows 电脑上双击启动安安。")
        return 1
    if sys.version_info < (3, 10) or sys.maxsize <= 2 ** 32:
        print("源码版需要 64 位 Python 3.10 或更新版本。免安装版无需安装 Python。")
        return 1
    mode = sys.argv[1] if len(sys.argv) > 1 else "start"
    if mode not in ("start", "build"):
        print("无法识别操作，请双击“启动安安”或“制作免安装版”。")
        return 1
    output = ROOT / "build"
    output.mkdir(exist_ok=True)
    log_path = output / "准备日志.txt"
    try:
        with log_path.open("w", encoding="utf-8") as log:
            python = prepare_environment(ROOT, log)
            if mode == "build":
                print("正在检查功能……", flush=True)
                run_checked([str(python), "-m", "pytest", "-q"], ROOT, log)
                print("正在制作免安装版，完成后会打开成品文件夹……", flush=True)
                run_checked([str(python), "scripts/构建.py"], ROOT, log)
                print("制作完成！双击成品文件夹中的“安安.exe”即可使用。", flush=True)
                os.startfile(str(ROOT / "dist/安安"))
                return 0
        launch(python, ROOT)
        return 0
    except (OSError, subprocess.SubprocessError, RuntimeError):
        with log_path.open("a", encoding="utf-8") as log:
            traceback.print_exc(file=log)
        print("暂时未能完成。如果正在准备组件，请确认网络可用后重新双击。", flush=True)
        print(f"排查记录保存在：{log_path}；窗口打不开时也请查看“启动日志.txt”。", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
