"""透明桌宠、拖动、缩放和托盘；不读取其他应用的输入。"""

import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QRectF, QStandardPaths
from PySide6.QtGui import QCursor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QMenu, QSlider, QSystemTrayIcon, QVBoxLayout, QWidget

from .animation import load_animations, resource_root
from .behavior import BehaviorController, load_behaviors
from .pointer import Gesture, look_direction
from .rendering import align_pixmap, blend_pixmaps, keep_static_body, remove_green_spill, stabilize_idle, stabilize_look
from .settings import load_settings, resize_position, save_settings, visible_position


class PetWindow(QWidget):
    def __init__(self, settings_path=None):
        super().__init__()
        self.settings_path = settings_path or Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)) / "偏好.json"
        self.preferences = load_settings(self.settings_path)
        self.clips = load_animations(resource_root())
        # 加载时只清理一次；各动作共用的帧只解码、去溢色一次。
        paths = {p for clip in self.clips.values() for p in clip.frames}
        cache = {p: remove_green_spill(QPixmap(str(p))) for p in paths}
        self.pixmaps = {key: [align_pixmap(cache[p], clip.anchor) for p in clip.frames] for key, clip in self.clips.items()}
        for key, clip in self.clips.items():
            policy = clip.stabilization
            if policy and policy.eyes:
                self.pixmaps[key] = stabilize_idle(self.pixmaps[key], policy.eyes, policy.radius)
            elif policy and policy.head_bottom is not None:
                self.pixmaps[key] = stabilize_look(self.pixmaps[key], self.pixmaps["idle"][0], policy.head_bottom, policy.body_top)
        self.frame = self.pixmaps["idle"][0]
        self.frame_signature = None
        self.visual_key = "idle"
        self.visual_index = 0
        self.transition_source = None
        self.transition_started = 0
        self.transition_body_top = None
        self.transition_duration = 0
        self.controller = BehaviorController({key: c.total_ms for key, c in self.clips.items()}, config=load_behaviors(resource_root(), self.clips))
        self.controller.quiet = self.preferences["quiet"]
        self.gesture = Gesture(QApplication.startDragDistance())
        self.origin_time = time.monotonic()
        self.previous_advance_ms = 0
        self.wander_fraction = 0.0
        self.hovering = False
        self.look_index = 0
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
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.timeout.connect(self.advance)
        self.timer.start(16)
        for display in QApplication.screens():
            self.watch_screen(display)
        QApplication.instance().screenAdded.connect(self.watch_screen)
        QApplication.instance().screenRemoved.connect(lambda _: self.ensure_visible())
        self.show()

    def now(self):
        return int((time.monotonic() - self.origin_time) * 1000)

    def act(self, action):
        self.controller.handle(action, self.now())
        self.refresh_frame(self.now())

    def create_menu(self):
        menu = QMenu(self)
        menu.addAction("显示安安", self.show_pet)
        menu.addAction("调整大小…", self.size_dialog)
        menu.addSeparator()
        menu.addAction("打招呼", lambda: self.act("waving"))
        for action, spec in self.controller.config.actions.items():
            if action != "look":
                menu.addAction(spec.label, lambda checked=False, key=action: self.act(key))
        menu.addAction("叫醒安安", lambda: self.act("wake"))
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
        elapsed = max(0, min(100, now - self.previous_advance_ms))
        self.previous_advance_ms = now
        before = self.controller.state
        if self.hovering:
            self.controller.handle("hover", now)
        state = self.controller.tick(now)
        if self.preferences["wander"] and not self.controller.quiet and before == "idle" and state == "look":
            self.act("running-left" if self.controller.rng.randrange(2) else "running-right")
            state = self.controller.state
        if self.preferences["wander"] and not self.controller.dragging and state.startswith("running-"):
            distance = self.wander_fraction + elapsed * 30 / 1000
            step = int(distance)
            self.wander_fraction = distance - step
            self.move(self.x() + (-step if state.endswith("left") else step), self.y())
            self.ensure_visible()
        else:
            self.wander_fraction = 0.0
        self.refresh_frame(now)

    def refresh_frame(self, now):
        key = self.controller.state
        index, following, amount = self.clips[key].sample(now - self.controller.started)
        if self.hovering and key == "idle":
            delta = QCursor.pos() - self.geometry().center()
            self.look_index = look_direction(delta.x(), delta.y(), self.look_index, max(8, self.width() * 0.06))
            key, index = "look", self.look_index
            following, amount = index, 0
        amount = round(amount * 16) / 16
        signature = key, index, following, amount
        clip = self.clips[key]
        turning = clip.stabilization is not None and clip.stabilization.head_bottom is not None and index != self.visual_index
        if key != self.visual_key or turning:
            policies = [self.clips[self.visual_key].stabilization, clip.stabilization]
            self.transition_body_top = max(p.body_top for p in policies) if all(policies) else None
            self.transition_duration = clip.transition_ms
            self.transition_source = self.frame if self.transition_duration else None
            self.transition_started = now
            self.visual_key = key
        self.visual_index = index
        if signature == self.frame_signature and self.transition_source is None:
            return
        pixmap = blend_pixmaps(self.pixmaps[key][index], self.pixmaps[key][following], amount)
        if self.transition_source is not None:
            progress = (now - self.transition_started) / self.transition_duration
            if progress >= 1:
                self.transition_source = None
            else:
                pixmap = blend_pixmaps(self.transition_source, pixmap, max(0, progress))
        if self.transition_source is not None:
            body_top = self.transition_body_top
        else:
            body_top = clip.stabilization.body_top if clip.stabilization else None
        if body_top is not None:
            pixmap = keep_static_body(pixmap, self.pixmaps["idle"][0], body_top)
        self.frame, self.frame_signature = pixmap, signature
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        # 所有动画画布使用共同底边和中线，避免切换时脚底漂移。
        rect = QRectF(0, 0, self.width(), self.height())
        painter.drawPixmap(rect, self.frame, QRectF(self.frame.rect()))

    def enterEvent(self, event):
        self.hovering = True
        self.refresh_frame(self.now())

    def leaveEvent(self, event):
        self.hovering = False
        self.refresh_frame(self.now())

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
            self.controller.set_drag_direction("left" if p.x() < self.previous_mouse_x else "right", self.now())
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
