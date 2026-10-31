"""透明桌宠、拖动、缩放和托盘；逗猫期间观察窗口外双击以收起玩具。"""

import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QRectF, QStandardPaths, Signal
from PySide6.QtGui import QCursor, QIcon, QPainter
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QMenu, QSlider, QSystemTrayIcon, QVBoxLayout, QWidget

from .animation import resource_root
from .appearance import AppearanceError, load_appearance
from .behavior import BehaviorController, load_behaviors
from .audio import PlayAudio
from .global_mouse import TeaserExitMonitor
from .play import PlayController, load_play_config
from .props import ActionFeedback, PlayProps
from .pointer import AttentionTracker, Gesture, look_direction
from .rendering import blend_pixmaps, keep_static_body
from .settings import load_settings, resize_position, save_settings, valid_pet_id, visible_position


class PetWindow(QWidget):
    exit_requested = Signal()

    def __init__(self, settings_path=None):
        super().__init__()
        self.settings_path = settings_path or Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)) / "偏好.json"
        self.preferences = load_settings(self.settings_path)
        self.data_root = self.settings_path.parent
        self.pets_root = self.data_root / "宠物"
        self.appearance_error = None
        selected = self.preferences["active_pet"]
        try:
            appearance = self.read_appearance(selected)
        except AppearanceError as error:
            self.appearance_error = str(error)
            appearance = self.read_appearance(None)
            self.preferences["active_pet"] = None
            try:
                save_settings(self.settings_path, self.preferences)
            except OSError:
                self.appearance_error += "；默认选择暂未保存，下次启动会重新检查"
        self.pet_name = appearance.name
        self.clips, self.pixmaps = appearance.clips, appearance.pixmaps
        self.frame = self.pixmaps["idle"][0]
        self.cat_frame = self.frame
        self.frame_signature = None
        self.last_render_ms = None
        self.render_domain = None
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
        self.attention = AttentionTracker()
        self.look_index = 0
        self.drag_offset = None
        self.previous_mouse_x = 0
        self.dialog = None
        self.play = PlayController(load_play_config(resource_root()))
        self.audio = PlayAudio(resource_root())
        self.props = PlayProps(self, resource_root())
        self.pending_play = None
        self.teaser_exit = None
        self.menu_open = False
        self.last_explicit_ms = -5000
        self.closed = False
        self.setWindowTitle(f"{self.pet_name} · 桌面宠物")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self.setToolTip(f"{self.pet_name}：单击跳跃，拖动移动，右键打开设置")
        self.resize(self.preferences["size"], self.preferences["size"])
        screen = QApplication.primaryScreen()
        area = screen.availableGeometry() if screen is not None else None
        pos = self.preferences["position"] or ([area.right() - self.width() - 30, area.bottom() - self.height() - 20] if area else [0, 0])
        self.move(*pos)
        self.ensure_visible()
        self.menu = self.create_menu()
        icon = QIcon(self.pixmaps["idle"][0])
        self.setWindowIcon(icon)
        self.tray = QSystemTrayIcon(icon, self)
        self.tray.setToolTip(f"{self.pet_name}桌面宠物")
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
        if self.appearance_error:
            self.tray.showMessage("已恢复默认安安", self.appearance_error)

    def read_appearance(self, pet_id):
        if pet_id is None:
            return load_appearance(resource_root())
        if not valid_pet_id(pet_id):
            raise AppearanceError("自定义宠物标识无效")
        target = self.pets_root / pet_id
        if not target.resolve().is_relative_to(self.pets_root.resolve()):
            raise AppearanceError("自定义宠物目录越界")
        return load_appearance(resource_root(), target)

    def update_appearance_menu(self):
        self.restore_default_action.setEnabled(self.preferences["active_pet"] is not None)
        selected = self.preferences["custom_pet"]
        available = selected is not None and selected != self.preferences["active_pet"]
        if available:
            try:
                self.read_appearance(selected)
            except AppearanceError:
                available = False
        self.custom_pet_action.setEnabled(available)

    def activate_custom_pet(self, pet_id):
        if not valid_pet_id(pet_id):
            self.appearance_error = "自定义宠物标识无效"
            self.tray.showMessage("外观未切换", self.appearance_error)
            return False
        return self.change_appearance(pet_id)

    def restore_default_pet(self):
        if self.preferences["active_pet"] is None:
            return True
        return self.change_appearance(None)

    def change_appearance(self, pet_id):
        try:
            appearance = self.read_appearance(pet_id)
            preferences = dict(self.preferences, active_pet=pet_id)
            if pet_id is not None:
                preferences["custom_pet"] = pet_id
            save_settings(self.settings_path, preferences)
        except (AppearanceError, OSError) as error:
            self.appearance_error = str(error)
            self.tray.showMessage("外观未切换", self.appearance_error)
            return False
        self.end_play("切换外观")
        now = self.now()
        self.controller.handle("drag_end", now)
        self.preferences = preferences
        self.pet_name = appearance.name
        self.clips, self.pixmaps = appearance.clips, appearance.pixmaps
        self.gesture = Gesture(QApplication.startDragDistance())
        self.drag_offset = None
        self.attention = AttentionTracker()
        self.look_index = 0
        self.transition_source = None
        self.transition_body_top = None
        self.transition_duration = 0
        self.transition_started = now
        self.visual_key, self.visual_index = "idle", 0
        self.frame_signature = self.render_domain = self.last_render_ms = None
        self.frame = self.cat_frame = self.pixmaps["idle"][0]
        self.last_explicit_ms = self.previous_advance_ms = now
        self.wander_fraction = 0.0
        self.appearance_error = None
        icon = QIcon(self.frame)
        self.setWindowIcon(icon)
        self.tray.setIcon(icon)
        self.setWindowTitle(f"{self.pet_name} · 桌面宠物")
        self.setToolTip(f"{self.pet_name}：单击跳跃，拖动移动，右键打开设置")
        self.tray.setToolTip(f"{self.pet_name}桌面宠物")
        self.show_pet_action.setText(f"显示{self.pet_name}")
        self.wake_pet_action.setText(f"叫醒{self.pet_name}")
        self.quit_pet_action.setText(f"退出{self.pet_name}")
        if self.dialog is not None:
            self.dialog.setWindowTitle(f"{self.pet_name}的大小")
        self.update_appearance_menu()
        self.update()
        return True

    def now(self):
        return int((time.monotonic() - self.origin_time) * 1000)

    def act(self, action):
        now = self.now()
        if action != "hover":
            self.last_explicit_ms = now
            self.end_play("手动动作")
        self.controller.handle(action, now)
        self.update_attention(now)
        self.refresh_frame(now)

    def create_menu(self):
        menu = QMenu(self)
        self.show_pet_action = menu.addAction(f"显示{self.pet_name}", self.show_pet)
        menu.addAction("调整大小…", self.size_dialog)
        menu.addSeparator()
        menu.addAction("打招呼", lambda: self.act("waving"))
        for action, spec in self.controller.config.actions.items():
            if action != "look":
                menu.addAction(spec.label, lambda checked=False, key=action: self.act(key))
        self.wake_pet_action = menu.addAction(f"叫醒{self.pet_name}", lambda: self.act("wake"))
        demo = menu.addMenu("已有动作演示")
        for title, key in (("环顾四周", "look"), ("向左走", "running-left"), ("向右走", "running-right"), ("专心思考", "running"), ("期待回应", "waiting"), ("仔细检查", "review"), ("有点失落", "failed")):
            demo.addAction(title, lambda checked=False, state=key: self.act(state))
        menu.addSeparator()
        menu.addAction("想吃零食吗", lambda: self.start_play("beg"))
        menu.addAction("喂零食", lambda: self.start_play("feed", "snack"))
        menu.addAction("喂冻干", lambda: self.start_play("feed", "freeze_dried"))
        self.teaser_action = menu.addAction("召唤逗猫棒", self.toggle_teaser)
        self.end_play_action = menu.addAction("结束本次互动", lambda: self.end_play("用户结束"))
        self.end_play_action.setEnabled(False)
        self.auto_beg_action = menu.addAction("自动索食")
        self.auto_beg_action.setCheckable(True)
        self.auto_beg_action.setChecked(self.preferences["auto_beg"])
        self.auto_beg_action.toggled.connect(self.set_auto_beg)
        self.sound_action = menu.addAction("猫叫声")
        self.sound_action.setCheckable(True)
        self.sound_action.setChecked(self.preferences["sound_enabled"])
        self.sound_action.toggled.connect(self.set_sound_enabled)
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
        menu.addSeparator()
        self.restore_default_action = menu.addAction("恢复默认安安", self.restore_default_pet)
        self.custom_pet_action = menu.addAction("切换到自定义宠物", lambda: self.activate_custom_pet(self.preferences["custom_pet"]))
        self.update_appearance_menu()
        menu.aboutToShow.connect(self.update_appearance_menu)
        self.quit_pet_action = menu.addAction(f"退出{self.pet_name}", self.quit)
        menu.aboutToShow.connect(lambda: self.set_menu_open(True))
        menu.aboutToHide.connect(lambda: self.set_menu_open(False))
        return menu

    def set_quiet(self, checked):
        if checked:
            self.end_play("开启安静模式")
        self.preferences["quiet"] = checked
        self.controller.quiet = checked
        self.sync_play(self.now())
        self.persist()

    def play_paused(self):
        return self.menu_open or self.dialog is not None or not self.isVisible() or self.closed

    def sync_play(self, now):
        active = self.play.mode != "none"
        paused = self.play_paused()
        awake = self.controller.state not in self.controller.config.exits
        auto_clock = (self.preferences["auto_beg"] and not self.controller.quiet and awake
                      and not paused and not self.controller.dragging and self.pending_play is None
                      and not active)
        can_start = (self.controller.state == "idle" and not self.attention.active
                     and now - self.last_explicit_ms >= 5000)
        view = self.play.tick(now, auto_clock, not paused, can_start)
        if active and view.mode == "none":
            self.controller.handle("idle", now)
        if view.mode in ("teaser", "teaser_swipe") and not paused:
            position, center = QCursor.pos(), self.geometry().center()
            view = self.play.set_target((position.x(), position.y()), (center.x(), center.y()), self.width(), now)
        self.audio.update(view, enabled=self.preferences["sound_enabled"], quiet=self.controller.quiet, paused=paused)
        self.update_props(view, now)
        self.sync_teaser_exit()
        self.update_play_menu()
        return view

    def sync_teaser_exit(self):
        teaser = self.play.mode in ('teaser', 'teaser_swipe') or (self.pending_play is not None and self.pending_play[0] == 'teaser')
        enabled = teaser and not self.play_paused() and not self.controller.dragging
        if enabled and self.teaser_exit is None:
            self.teaser_exit = TeaserExitMonitor(int(self.winId()), self, native=QApplication.platformName() == 'windows')
            self.teaser_exit.double_clicked.connect(self.handle_teaser_double_click, Qt.ConnectionType.QueuedConnection)
        if self.teaser_exit is not None:
            was_enabled = self.teaser_exit.enabled
            self.teaser_exit.set_enabled(enabled)
            if enabled and not was_enabled and self.teaser_exit.error:
                self.props.show_feedback(self.play.view, '双击退出暂不可用，请右键收起')

    def handle_teaser_double_click(self, generation):
        monitor = self.teaser_exit
        teaser = self.play.mode in ('teaser', 'teaser_swipe') or (self.pending_play is not None and self.pending_play[0] == 'teaser')
        if monitor is not None and monitor.enabled and monitor.generation == generation and teaser and not self.play_paused() and not self.controller.dragging:
            self.end_play('窗口外双击')

    def shutdown_teaser_exit(self):
        if self.teaser_exit is not None:
            self.teaser_exit.close()

    def update_props(self, view, now):
        elapsed = now - self.controller.started
        feedback = None
        if self.controller.state == 'yawn' and 400 <= elapsed < 1050:
            feedback = ActionFeedback('嗷呜～')
        elif self.controller.state == 'waving':
            end = self.clips['waving'].total_ms - 320
            if 260 <= elapsed < end:
                feedback = ActionFeedback('喵～', '♡', elapsed - 260, min(1.0, (end - elapsed) / 240))
        self.props.update(view, visible=self.isVisible() and not self.closed,
                          paused=self.play_paused(), action_feedback=feedback)

    def update_play_menu(self):
        if hasattr(self, "teaser_action"):
            teaser = self.play.mode in ("teaser", "teaser_swipe") or (self.pending_play is not None and self.pending_play[0] == "teaser")
            self.teaser_action.setText("收起逗猫棒" if teaser else "召唤逗猫棒")
            self.end_play_action.setEnabled(self.play.mode != "none" or self.pending_play is not None)

    def start_play(self, kind, food="freeze_dried"):
        if kind not in ("beg", "feed", "teaser") or (kind != "teaser" and food not in ("snack", "freeze_dried")):
            raise ValueError("不支持的趣味互动或食物")
        now = self.now()
        self.last_explicit_ms = now
        self.sync_play(now)
        continuing_meal = kind == "feed" and self.play.mode == "begging"
        if not continuing_meal:
            self.end_play("切换互动")
        if self.controller.state in self.controller.config.exits:
            self.pending_play = (kind, food)
            self.controller.handle("wake", now)
        else:
            self.controller.handle("idle", now)
            self.play.request(kind, now, food)
        self.update_attention(now)
        self.sync_play(now)
        self.refresh_frame(now)

    def end_play(self, reason="用户结束"):
        if self.teaser_exit is not None:
            self.teaser_exit.set_enabled(False)
        now = self.now()
        self.last_explicit_ms = now
        active = self.play.mode != "none"
        self.pending_play = None
        self.play.cancel(now, reason)
        self.audio.close()
        self.props.clear()
        if active:
            self.controller.handle("idle", now)
        self.update_play_menu()
        self.refresh_frame(now)

    def toggle_teaser(self):
        if self.play.mode in ("teaser", "teaser_swipe") or (self.pending_play is not None and self.pending_play[0] == "teaser"):
            self.end_play("收起逗猫棒")
        else:
            self.start_play("teaser")

    def set_auto_beg(self, checked):
        self.sync_play(self.now())
        self.preferences["auto_beg"] = checked
        if not checked and self.play.origin == "auto" and self.play.mode == "begging":
            self.end_play("关闭自动索食")
        self.auto_beg_action.setChecked(checked)
        self.sync_play(self.now())
        self.persist()

    def set_sound_enabled(self, checked):
        self.preferences["sound_enabled"] = checked
        self.sound_action.setChecked(checked)
        self.sync_play(self.now())
        self.persist()

    def set_menu_open(self, opened):
        # 边界先结算旧区间，再切换标记，关闭时不补算菜单停留时间。
        now = self.now()
        self.last_explicit_ms = now
        self.sync_play(now)
        self.menu_open = opened
        self.update_attention(now)
        self.sync_play(now)

    def set_wander(self, checked):
        self.preferences["wander"] = checked
        self.persist()

    def tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.show_pet()

    def show_pet(self):
        self.last_explicit_ms = self.now()
        self.ensure_visible()
        self.show()
        self.raise_()
        self.sync_play(self.now())

    def watch_screen(self, screen):
        screen.availableGeometryChanged.connect(lambda _: self.ensure_visible())
        screen.geometryChanged.connect(lambda _: self.ensure_visible())
        self.ensure_visible()

    def advance(self):
        now = self.now()
        elapsed = max(0, min(100, now - self.previous_advance_ms))
        self.previous_advance_ms = now
        before = self.controller.state
        self.update_attention(now)
        view = self.sync_play(now)
        if view.mode == "none":
            if self.attention.active:
                self.controller.handle("hover", now)
            state = self.controller.tick(now)
            if self.pending_play is not None and state == "idle":
                kind, food = self.pending_play
                self.pending_play = None
                self.play.request(kind, now, food)
                self.sync_play(now)
            elif self.preferences["wander"] and not self.controller.quiet and before == "idle" and state == "look":
                self.controller.handle("running-left" if self.controller.rng.randrange(2) else "running-right", now)
        state = self.controller.state
        if self.play.mode == "none" and self.preferences["wander"] and not self.controller.dragging and state.startswith("running-"):
            distance = self.wander_fraction + elapsed * 30 / 1000
            step = int(distance)
            self.wander_fraction = distance - step
            self.move(self.x() + (-step if state.endswith("left") else step), self.y())
            self.ensure_visible()
        else:
            self.wander_fraction = 0.0
        self.refresh_frame(now)

    def update_attention(self, now):
        position, center = QCursor.pos(), self.geometry().center()
        eligible = self.play.mode == "none" and self.pending_play is None and not self.menu_open and self.isVisible() and self.controller.state == "idle" and not self.controller.dragging and not self.menu.isVisible() and self.dialog is None
        self.attention.update((position.x(), position.y()), (center.x(), center.y()), self.width(), now, eligible)

    def refresh_frame(self, now):
        view = self.play.view
        self.update_props(view, now)
        active = view.mode != "none"
        render_now = view.session_elapsed_ms if active else now
        render_domain = ("play", view.session_id) if active else ("normal",)
        domain_changed = self.render_domain is not None and render_domain != self.render_domain
        key = view.clip if active else self.controller.state
        elapsed = view.clip_elapsed_ms if active else now - self.controller.started
        index, following, amount = self.clips[key].sample(elapsed)
        if active and key == "look":
            index = following = view.look_index
            amount = 0
            self.look_index = index
        elif self.attention.active and key == "idle":
            delta = QCursor.pos() - self.geometry().center()
            self.look_index = look_direction(delta.x(), delta.y(), self.look_index, max(8, self.width() * 0.06))
            key, index = "look", self.look_index
            following, amount = index, 0
        amount = round(amount * 16) / 16
        signature = key, index, following, amount, render_domain, self.props.signature(view)
        clip = self.clips[key]
        turning = clip.stabilization is not None and clip.stabilization.head_bottom is not None and index != self.visual_index
        pose_changed = key != self.visual_key or turning
        if pose_changed or (domain_changed and self.transition_source is not None):
            if pose_changed:
                policies = [self.clips[self.visual_key].stabilization, clip.stabilization]
                self.transition_body_top = max(p.body_top for p in policies) if all(policies) else None
            self.transition_duration = clip.transition_ms
            # 道具不进入过渡源，避免反复把猫碗叠回下一帧。
            source = self.cat_frame if active or self.frame_signature and self.frame_signature[-1][0] != "none" else self.frame
            self.transition_source = source if self.transition_duration else None
            self.transition_started = render_now
            self.visual_key = key
        self.visual_index = index
        self.render_domain = render_domain
        if signature == self.frame_signature and (self.transition_source is None or render_now == self.last_render_ms):
            return
        pixmap = blend_pixmaps(self.pixmaps[key][index], self.pixmaps[key][following], amount)
        if self.transition_source is not None:
            progress = (render_now - self.transition_started) / self.transition_duration
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
        self.last_render_ms = render_now
        self.cat_frame = pixmap
        self.frame, self.frame_signature = self.props.compose(pixmap, view), signature
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        # 所有动画画布使用共同底边和中线，避免切换时脚底漂移。
        rect = QRectF(0, 0, self.width(), self.height())
        painter.drawPixmap(rect, self.frame, QRectF(self.frame.rect()))

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
                now = self.now()
                self.last_explicit_ms = now
                mode = self.play.mode
                if self.play.click(now):
                    if mode in ("serving", "eating"):
                        self.props.show_feedback(self.play.view, "安安正在吃呢")
                    elif mode == "satisfied":
                        self.props.show_feedback(self.play.view, "吃饱啦，谢谢你")
                    self.sync_play(now)
                    self.refresh_frame(now)
                else:
                    self.act("click")

    def contextMenuEvent(self, event):
        self.menu.exec(event.globalPos())

    def ensure_visible(self):
        screens = [(r.x(), r.y(), r.width(), r.height()) for r in [s.availableGeometry() for s in QApplication.screens()]]
        if screens:
            self.move(*visible_position(self.x(), self.y(), self.width(), self.height(), screens))
        if hasattr(self, "play"):
            self.update_props(self.play.view, self.now())

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
        self.last_explicit_ms = self.now()
        self.sync_play(self.last_explicit_ms)
        self.dialog = QDialog(self)
        self.dialog.setWindowTitle(f"{self.pet_name}的大小")
        layout = QVBoxLayout(self.dialog)
        label = QLabel(f"大小：{self.width()} 像素")
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(100, 400)
        slider.setValue(self.width())
        slider.valueChanged.connect(lambda value: (label.setText(f"大小：{value} 像素"), self.set_size(value)))
        layout.addWidget(label)
        layout.addWidget(slider)
        self.dialog.finished.connect(self.finish_size_dialog)
        self.dialog.resize(300, 100)
        self.dialog.show()
        self.sync_play(self.now())

    def finish_size_dialog(self, result):
        now = self.now()
        self.last_explicit_ms = now
        self.sync_play(now)
        self.dialog = None
        self.sync_play(now)

    def hideEvent(self, event):
        if hasattr(self, "play"):
            self.end_play("隐藏安安")
        super().hideEvent(event)

    def closeEvent(self, event):
        self.closed = True
        self.end_play("关闭安安")
        self.timer.stop()
        self.tray.hide()
        if self.dialog is not None:
            self.dialog.close()
        super().closeEvent(event)
        self.exit_requested.emit()

    def persist(self):
        self.preferences["position"] = [self.x(), self.y()]
        save_settings(self.settings_path, self.preferences)

    def quit(self):
        self.closed = True
        self.end_play("退出安安")
        self.timer.stop()
        self.persist()
        self.tray.hide()
        QApplication.instance().quit()
