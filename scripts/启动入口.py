"""供 PyInstaller 使用的绝对导入入口。"""

from anan_pet.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
