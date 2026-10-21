"""检查新增动作资源和实际 Qt 窗口交互。"""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PySide6.QtCore import Qt, QPoint
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from anan_pet.animation import load_animations, resource_root
from anan_pet.window import PetWindow


def test_new_actions_have_transparent_frames():
    clips = load_animations(resource_root())
    for name in ("scratch", "wash", "yawn", "stretch", "prone_enter", "prone_sleep", "prone_exit", "supine_enter", "supine_sleep", "supine_exit"):
        assert name in clips, f"缺少新动画：{name}"
        for path in clips[name].frames:
            with Image.open(path) as im:
                assert im.size == (256, 256)
                assert im.mode == "RGBA"
                assert im.getchannel("A").getextrema()[0] == 0
                assert im.getchannel("A").getbbox() is not None


def test_real_window_hover_click_resize_and_restore(tmp_path):
    app = QApplication.instance() or QApplication([])
    path = tmp_path / "偏好.json"
    w = PetWindow(path)
    w.timer.stop()
    QTest.mouseMove(w, QPoint(80, 80))
    assert w.controller.state == "idle"
    QTest.mouseClick(w, Qt.MouseButton.LeftButton, pos=QPoint(80, 80))
    assert w.controller.state == "jumping"
    w.set_size(330)
    assert w.size().width() == 330
    assert not w.grab().toImage().isNull()
    w.persist()
    w.tray.hide()
    w.close()
    other = PetWindow(path)
    other.timer.stop()
    assert other.width() == 330
    other.tray.hide()
    other.close()


def test_window_drag_does_not_jump(tmp_path):
    app = QApplication.instance() or QApplication([])
    w = PetWindow(tmp_path / "偏好.json")
    w.timer.stop()
    QTest.mousePress(w, Qt.MouseButton.LeftButton, pos=QPoint(50, 50))
    QTest.mouseMove(w, QPoint(100, 50))
    QTest.mouseRelease(w, Qt.MouseButton.LeftButton, pos=QPoint(100, 50))
    assert w.controller.state == "idle"
    assert not w.controller.dragging
    w.tray.hide()
    w.close()


def test_screen_change_and_show_restore_visible_position(tmp_path):
    app = QApplication.instance() or QApplication([])
    w = PetWindow(tmp_path / "偏好.json")
    w.timer.stop()
    screen = app.primaryScreen()
    w.move(-5000, -5000)
    screen.availableGeometryChanged.emit(screen.availableGeometry())
    assert screen.availableGeometry().intersects(w.geometry())
    w.hide()
    w.move(-5000, -5000)
    w.menu.actions()[0].trigger()
    assert screen.availableGeometry().intersects(w.geometry())
    w.tray.hide()
    w.close()
