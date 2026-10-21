"""透明桌宠、拖动、缩放和托盘；不读取其他应用的输入。"""

import math
import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QRectF, QStandardPaths
from PySide6.QtGui import QCursor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QMenu, QSlider, QSystemTrayIcon, QVBoxLayout, QWidget

from .animation import load_animations, resource_root
from .behavior import BehaviorController
from .pointer import Gesture
from .settings import load_settings, resize_position, save_settings, visible_position


class PetWindow(QWidget):
    def __init__(self, settings_path=None):
        super().__init__()
        self.settings_path = settings_path or Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)) / "偏好.json"
        self.preferences = load_settings(self.settings_path)
        self.clips = load_animations(resource_root())
        self.pixmaps = {key: [QPixmap(str(p)) for p in clip.frames] for key, clip in self.clips.items()}
        self.controller = BehaviorController({key: c.total_ms for key, c in self.clips.items()})
        self.controller.quiet = self.preferences["quiet"]
        self.gesture = Gesture(QApplication.startDragDistance())
        self.origin_time = time.monotonic()
        self.hovering = False
        self.drag_offset = None
        self.previous_mouse_x = 0
        self.dialog = None
        self.setWindowTitle("安安 · 桌面宠物")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self.setToolTip("安安：单击跳跃，拖动移动，右键打开设置")
        self.resize(self.preferences["size"], self.preferences["size"])
        screen = QApplication.primaryScreen().availableGeometry()
        pos = self.preferences["position"] or [screen.right() - self.width() - 30, screen.bottom() - self.height() - 20]
        self.move(*pos)
        self.ensure_visible()
        self.menu = self.create_menu()
        icon = QIcon(self.pixmaps["idle"][0])
        self.setWindowIcon(icon)
        self.tray = QSystemTrayIcon(icon, self)
        self.tray.setToolTip("安安桌面宠物")
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self.tray_activated)
        self.tray.show()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.advance)
        self.timer.start(33)
        for display in QApplication.screens():
            self.watch_screen(display)
        QApplication.instance().screenAdded.connect(self.watch_screen)
        QApplication.instance().screenRemoved.connect(lambda _: self.ensure_visible())
        self.show()

    def now(self):
        return int((time.monotonic() - self.origin_time) * 1000)

    def act(self, action):
        self.controller.handle(action, self.now())
        self.update()

    def create_menu(self):
        menu = QMenu(self)
        menu.addAction("显示安安", self.show_pet)
        menu.addAction("调整大小…", self.size_dialog)
        menu.addSeparator()
        for title, action in (("打招呼", "waving"), ("挠耳朵", "scratch"), ("舔爪洗脸", "wash"), ("打哈欠", "yawn"), ("伸懒腰", "stretch"), ("趴下睡觉", "sleep"), ("仰卧露肚皮睡", "supine"), ("叫醒安安", "wake")):
            if action in ("sleep", "supine", "wake") or action in self.clips:
                menu.addAction(title, lambda checked=False, key=action: self.act(key))
        demo = menu.addMenu("已有动作演示")
        for title, key in (("环顾四周", "look"), ("向左走", "running-left"), ("向右走", "running-right"), ("专心思考", "running"), ("期待回应", "waiting"), ("仔细检查", "review"), ("有点失落", "failed")):
            demo.addAction(title, lambda checked=False, state=key: self.act(state))
        menu.addSeparator()
        quiet = menu.addAction("安静模式")
        quiet.setCheckable(True)
        quiet.setChecked(self.preferences["quiet"])
        quiet.toggled.connect(self.set_quiet)
        wander = menu.addAction("偶尔散步")
        wander.setCheckable(True)
        wander.setChecked(self.preferences["wander"])
        wander.toggled.connect(self.set_wander)
        menu.addAction("暂时隐藏（托盘可恢复）", self.hide)
        menu.addAction("退出安安", self.quit)
        return menu

    def set_quiet(self, checked):
        self.preferences["quiet"] = checked
        self.controller.quiet = checked
        self.persist()

    def set_wander(self, checked):
        self.preferences["wander"] = checked
        self.persist()

    def tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.show_pet()

    def show_pet(self):
        self.ensure_visible()
        self.show()
        self.raise_()

    def watch_screen(self, screen):
        screen.availableGeometryChanged.connect(lambda _: self.ensure_visible())
        screen.geometryChanged.connect(lambda _: self.ensure_visible())
        self.ensure_visible()

    def advance(self):
        now = self.now()
        before = self.controller.state
        state = self.controller.tick(now)
        if self.preferences["wander"] and not self.controller.quiet and before == "idle" and state == "look":
            self.act("running-left" if self.controller.rng.randrange(2) else "running-right")
            state = self.controller.state
        if self.preferences["wander"] and not self.controller.dragging and state.startswith("running-"):
            self.move(self.x() + (-1 if state.endswith("left") else 1), self.y())
            self.ensure_visible()
        self.update()

    def paintEvent(self, event):
        key = self.controller.state
        index = self.clips[key].frame_index(self.now() - self.controller.started)
        if self.hovering and key == "idle":
            delta = QCursor.pos() - self.geometry().center()
            angle = math.degrees(math.atan2(delta.x(), -delta.y())) % 360
            key, index = "look", round(angle / 22.5) % 16
        pixmap = self.pixmaps[key][index]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        # 所有动画画布使用共同底边和中线，避免切换时脚底漂移。
        rect = QRectF(0, 0, self.width(), self.height())
        painter.drawPixmap(rect, pixmap, QRectF(pixmap.rect()))

    def enterEvent(self, event):
        self.hovering = True

    def leaveEvent(self, event):
        self.hovering = False

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            p = event.globalPosition().toPoint()
            self.gesture.press(p.x(), p.y())
            self.drag_offset = p - self.pos()
            self.previous_mouse_x = p.x()

    def mouseMoveEvent(self, event):
        p = event.globalPosition().toPoint()
        if self.gesture.origin is not None and self.gesture.move(p.x(), p.y()):
            if not self.controller.dragging:
                self.act("drag_start")
            self.controller.state = "running-left" if p.x() < self.previous_mouse_x else "running-right"
            self.move(p - self.drag_offset)
            self.previous_mouse_x = p.x()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            clicked = self.gesture.release()
            if self.controller.dragging:
                self.act("drag_end")
                self.ensure_visible()
                self.persist()
            elif clicked:
                self.act("click")

    def contextMenuEvent(self, event):
        self.menu.exec(event.globalPos())

    def ensure_visible(self):
        screens = [(r.x(), r.y(), r.width(), r.height()) for r in [s.availableGeometry() for s in QApplication.screens()]]
        if screens:
            self.move(*visible_position(self.x(), self.y(), self.width(), self.height(), screens))

    def set_size(self, size):
        x, y = resize_position(self.x(), self.y(), self.width(), self.height(), size, size)
        self.resize(size, size)
        self.move(x, y)
        self.ensure_visible()
        self.preferences["size"] = size
        self.persist()

    def size_dialog(self):
        if self.dialog is not None:
            self.dialog.show()
            self.dialog.raise_()
            return
        self.dialog = QDialog(self)
        self.dialog.setWindowTitle("安安的大小")
        layout = QVBoxLayout(self.dialog)
        label = QLabel(f"大小：{self.width()} 像素")
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(100, 400)
        slider.setValue(self.width())
        slider.valueChanged.connect(lambda value: (label.setText(f"大小：{value} 像素"), self.set_size(value)))
        layout.addWidget(label)
        layout.addWidget(slider)
        self.dialog.finished.connect(lambda _: setattr(self, "dialog", None))
        self.dialog.resize(300, 100)
        self.dialog.show()

    def persist(self):
        self.preferences["position"] = [self.x(), self.y()]
        save_settings(self.settings_path, self.preferences)

    def quit(self):
        self.persist()
        self.tray.hide()
        QApplication.instance().quit()
