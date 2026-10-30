"""源码入口和打包入口共用 main。"""

import argparse
import sys


def main():
    parser = argparse.ArgumentParser(description="安安桌面宠物")
    parser.add_argument("--smoke-test", action="store_true", help="启动资源和窗口后自动退出，供打包验证")
    options = parser.parse_args()
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from .window import PetWindow
    app = QApplication(sys.argv[:1])
    app.setApplicationName("安安桌面宠物")
    app.setOrganizationName("安安")
    app.setQuitOnLastWindowClosed(False)
    window = PetWindow()
    window.exit_requested.connect(app.quit)
    app.aboutToQuit.connect(window.shutdown_teaser_exit)
    if options.smoke_test:
        QTimer.singleShot(1500, app.quit)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
