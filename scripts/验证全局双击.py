"""只点击独立辅助进程的按钮，验证真实桌面逗猫退出与点击放行。"""

import argparse
import ctypes
import json
import multiprocessing
import os
from pathlib import Path
import sys
import tempfile
import time

os.environ["QT_QPA_PLATFORM"] = "windows"
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton

from anan_pet.global_mouse import _MouseData, _Point, _Rect, _WinApi
from anan_pet.window import PetWindow


def _helper(connection):
    app = QApplication([])

    class Button(QPushButton):
        def __init__(self):
            super().__init__("安安原生鼠标验证\n只会点击这个辅助按钮")
            self.counts = {"按下": 0, "松开": 0, "双击": 0, "点击": 0}
            self.clicked.connect(lambda: self._count("点击"))

        def _count(self, key):
            self.counts[key] += 1

        def mousePressEvent(self, event):
            self._count("按下")
            super().mousePressEvent(event)

        def mouseReleaseEvent(self, event):
            self._count("松开")
            super().mouseReleaseEvent(event)

        def mouseDoubleClickEvent(self, event):
            self._count("双击")
            super().mouseDoubleClickEvent(event)

    button = Button()
    button.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
    button.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    area = app.primaryScreen().availableGeometry()
    button.resize(min(420, area.width() // 2), min(240, area.height() // 2))
    button.move(area.center() - button.rect().center())
    button.show()
    app.processEvents()
    connection.send({"窗口": int(button.winId())})

    def poll():
        if connection.poll():
            request = connection.recv()
            if request == "计数":
                connection.send(dict(button.counts))
            elif request == "退出":
                app.quit()

    timer = QTimer()
    timer.timeout.connect(poll)
    timer.start(10)
    app.exec()


class _MouseInput(ctypes.Structure):
    _fields_ = [("dx", ctypes.c_int32), ("dy", ctypes.c_int32),
                ("mouseData", ctypes.c_uint32), ("dwFlags", ctypes.c_uint32),
                ("time", ctypes.c_uint32), ("dwExtraInfo", ctypes.c_size_t)]


class _Input(ctypes.Structure):
    # 这里只发送鼠标输入；该字段的大小与 INPUT 联合体相同。
    _fields_ = [("type", ctypes.c_uint32), ("mouse", _MouseInput)]


class _InvisiblePet(PetWindow):
    def show(self):
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setWindowOpacity(0)
        super().show()


def _receive(connection, timeout=5):
    deadline = time.monotonic() + timeout
    while not connection.poll():
        if time.monotonic() >= deadline:
            raise RuntimeError("辅助窗口响应超时")
        QTest.qWait(10)
    return connection.recv()


def verify():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    api = _WinApi()
    user32 = api.user32
    for name, arguments, result in [
        ("WindowFromPoint", [_Point], ctypes.c_void_p),
        ("GetCursorPos", [ctypes.POINTER(_Point)], ctypes.c_int),
        ("SetCursorPos", [ctypes.c_int, ctypes.c_int], ctypes.c_int),
        ("SendInput", [ctypes.c_uint32, ctypes.POINTER(_Input), ctypes.c_int], ctypes.c_uint32),
    ]:
        function = getattr(user32, name)
        function.argtypes, function.restype = arguments, result
    original = _Point()
    assert user32.GetCursorPos(ctypes.byref(original)), "无法读取鼠标原位置"
    context = multiprocessing.get_context("spawn")
    connection, child = context.Pipe()
    helper = context.Process(target=_helper, args=(child,), name="安安鼠标验证辅助窗口")
    pet, hooks, pressed = None, [], False
    helper.start()
    try:
        helper_handle = _receive(connection)["窗口"]
        rect = _Rect()
        assert user32.GetWindowRect(helper_handle, ctypes.byref(rect)), "辅助窗口已关闭"
        center = ((rect.left + rect.right) // 2, (rect.top + rect.bottom) // 2)

        def move(x, y):
            assert user32.WindowFromPoint(_Point(x, y)) == helper_handle, "目标位置不是自有辅助窗口，停止注入"
            assert user32.SetCursorPos(x, y), "无法移动到辅助按钮"
            QTest.qWait(35)

        def button(down):
            nonlocal pressed
            point = _Point()
            assert user32.GetCursorPos(ctypes.byref(point))
            assert user32.WindowFromPoint(point) == helper_handle, "鼠标已离开自有辅助窗口，停止注入"
            event = _Input(type=0, mouse=_MouseInput(dwFlags=0x2 if down else 0x4))
            assert user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(event)) == 1, "鼠标注入未完成"
            pressed = down
            QTest.qWait(35)

        def click():
            button(True)
            button(False)

        with tempfile.TemporaryDirectory(prefix="安安原生验证-") as folder:
            pet = _InvisiblePet(Path(folder) / "偏好.json")
            pet.timer.stop()
            pet.tray.hide()
            pet.move(app.primaryScreen().availableGeometry().topLeft())
            pet.preferences["sound_enabled"] = False
            app.processEvents()

            def start():
                pet.start_play("teaser")
                pet.props.clear()
                assert pet.play.mode == "teaser"
                assert pet.teaser_exit.enabled and pet.teaser_exit.error is None, pet.teaser_exit.error
                hook = pet.teaser_exit._hook
                assert hook is not None and hook.thread.is_alive()
                hooks.append(hook)

            def double_click():
                click()
                click()
                QTest.qWait(120)
                assert pet.play.mode == "none", "窗口外双击未结束逗猫"
                assert not pet.teaser_exit.enabled
                assert not hooks[-1].thread.is_alive(), "退出后监听线程仍存在"
                assert hooks[-1].error is None, hooks[-1].error

            start()
            move(*center)
            click()
            assert pet.play.mode == "teaser", "单击误触退出"
            QTest.qWait(user32.GetDoubleClickTime() + 50)
            button(True)
            move(center[0] + 60, center[1])
            move(*center)
            button(False)
            assert pet.play.mode == "teaser", "拖动返回误触退出"
            QTest.qWait(user32.GetDoubleClickTime() + 50)
            double_click()
            for _ in range(3):
                start()
                QTest.qWait(user32.GetDoubleClickTime() + 50)
                double_click()
            connection.send("计数")
            counts = _receive(connection)
            assert counts["松开"] == 10 and counts["点击"] == 10, counts
            assert counts["双击"] >= 4, counts
            assert all(not hook.thread.is_alive() and hook.error is None for hook in hooks)
            # 只替代本监听的退出消息投递，验证真实消息等待仍能自行结束。
            start()
            failed_post_hook = hooks[-1]
            original_post = failed_post_hook._api.user32.PostThreadMessageW

            def fail_post(*args):
                ctypes.set_last_error(5)
                return 0

            failed_post_hook._api.user32.PostThreadMessageW = fail_post
            try:
                started = time.monotonic()
                pet.end_play("验证退出消息投递失败")
                failed_post_ms = round((time.monotonic() - started) * 1000)
                assert not failed_post_hook.thread.is_alive(), "退出消息失败后仍遗留真实监听线程"
                assert failed_post_hook.error and "投递失败" in failed_post_hook.error
                assert failed_post_ms < 750, "异常停止耗时过长"
            finally:
                failed_post_hook._api.user32.PostThreadMessageW = original_post
            return {"结果": "通过", "单击不退出": True, "拖动不退出": True,
                    "双击退出且正常放行": True, "重复双击会话": len(hooks) - 1,
                    "监听均已释放": True, "辅助进程按钮": counts,
                    "退出消息投递失败也释放": True, "异常停止耗时毫秒": failed_post_ms,
                    "双击时限毫秒": user32.GetDoubleClickTime(),
                    "结构字节": {"鼠标钩子": ctypes.sizeof(_MouseData),
                               "输入": ctypes.sizeof(_Input)}}
    finally:
        if pet is not None:
            pet.shutdown_teaser_exit()
            pet.tray.hide()
            pet.close()
        # 异常时也解除本脚本按下的左键，再还原鼠标，避免留下按键状态。
        if pressed:
            event = _Input(type=0, mouse=_MouseInput(dwFlags=0x4))
            user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(event))
        user32.SetCursorPos(original.x, original.y)
        if helper.is_alive():
            connection.send("退出")
            helper.join(3)
            if helper.is_alive():
                helper.terminate()
                helper.join(3)
        connection.close()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    parser = argparse.ArgumentParser(description="仅操作自有辅助按钮的 Windows 原生端到端验证")
    parser.add_argument("--output", type=Path, help="可选：保存中文 JSON 验证结果")
    arguments = parser.parse_args()
    result = verify()
    if arguments.output:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
