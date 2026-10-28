"""在 Windows 中打包完整运行环境，输出可直接解压使用的 ZIP。"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image
from 构建环境 import build_environment

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "src"))
from anan_pet import __version__

if sys.platform != "win32":
    raise SystemExit("请在 Windows x64 环境构建，或使用仓库的 GitHub Actions。")
if sys.maxsize <= 2 ** 32:
    raise SystemExit("请使用 64 位 Python。")
output = root / "dist"
output.mkdir(exist_ok=True)
icon = root / "build/安安.ico"
icon.parent.mkdir(exist_ok=True)
Image.open(root / "assets/frames/idle/00.png").save(icon, sizes=[(32, 32), (48, 48), (128, 128), (256, 256)])
subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed", "--name", "安安", "--icon", str(icon), "--paths", str(root / "src"), "--add-data", str(root / "assets") + os.pathsep + "assets", "--distpath", str(output), "--workpath", str(root / "build/pyinstaller"), "--specpath", str(root / "build"), str(root / "scripts/启动入口.py")], cwd=root, check=True, env=build_environment(os.environ, sys.executable, sys.base_prefix))
folder = output / "安安"
subprocess.run([str(folder / "安安.exe"), "--smoke-test"], cwd=folder, check=True, timeout=60)
try:
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True, stderr=subprocess.DEVNULL).strip()
    dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=root, text=True, stderr=subprocess.DEVNULL).strip())
except (OSError, subprocess.CalledProcessError):
    commit, dirty = "未知（来自源码压缩包或未安装 Git）", None
(folder / "版本.json").write_text(json.dumps({"版本": __version__, "源码提交": commit, "构建时有未提交修改": dirty}, ensure_ascii=False, indent=2), encoding="utf-8")
shutil.copy2(root / "docs/构建与使用.md", folder / "使用说明.md")
shutil.copy2(root / "使用说明.txt", folder / "使用说明.txt")
# Release 附件使用 ASCII 技术文件名，避免上传时中文名被重命名导致校验清单失配。
archive = Path(shutil.make_archive(str(output / f"anan-Windows-x64-v{__version__}"), "zip", output, "安安"))
checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
(output / "SHA256SUMS.txt").write_text(checksum + "  " + archive.name + "\n", encoding="utf-8")
print(f"构建成功：{archive}\nSHA-256：{checksum}")
