"""猫碗分层绘制与不接受输入的小型气泡、羽毛棒装饰。"""

import math

from PySide6.QtCore import QPoint, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QWidget


class DecorationWindow(QWidget):
    def __init__(self, parent, name):
        super().__init__(parent)
        self.setObjectName(name)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowTransparentForInput
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.text = ""
        self.pixmap = None
        self.font = QFont("Microsoft YaHei", 10)
        self.effect = "♪"
        self.effect_ms = 0
        self.content_signature = None

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        if self.pixmap is not None:
            painter.drawPixmap(self.rect(), self.pixmap)
        elif self.text:
            painter.setPen(QColor("#b99b88"))
            painter.setBrush(QColor(255, 248, 238, 245))
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(1, 28, -1, -1), 14, 14)
            painter.setFont(self.font)
            painter.setPen(QColor("#654936"))
            painter.drawText(self.rect().adjusted(10, 30, -10, -4), Qt.AlignmentFlag.AlignCenter, self.text)
            # 固定三个短命图形，只根据会话时间绘制，不创建额外窗口或计时器。
            for index in range(3):
                progress = ((self.effect_ms + index * 550) % 1800) / 1800
                painter.setOpacity(1 - progress)
                painter.setPen(QColor("#c48b70" if self.effect == "♪" else "#cc8199"))
                x = self.width() * (index + 1) / 4 + math.sin(progress * math.pi * 2) * 4
                y = 27 - progress * 22
                painter.drawText(QRectF(x - 9, y - 15, 18, 20), Qt.AlignmentFlag.AlignCenter, self.effect)


class PlayProps:
    def __init__(self, parent, root):
        self.parent = parent
        directory = root / "props"
        names = ["bowl_back", "bowl_front", "teaser"] + [f"{food}-{level}" for food in ("snack", "freeze_dried") for level in (1, 2, 3)]
        self.images = {name: QPixmap(str(directory / f"{name}.png")) for name in names}
        self.bubble = DecorationWindow(parent, "anan-play-bubble")
        self.toy = DecorationWindow(parent, "anan-play-toy")
        self.toy.pixmap = self.images["teaser"]
        self.toy.resize(80, 100)
        self.feedback = None

    def screen_rects(self):
        return [screen.availableGeometry() for screen in QApplication.screens()]

    @staticmethod
    def _place(window, desired, screens):
        def distance(rect):
            return (rect.center() - desired).manhattanLength()
        area = next((rect for rect in screens if rect.contains(desired)), None) or min(screens, key=distance)
        x = max(area.left(), min(desired.x(), area.right() - window.width() + 1))
        y = max(area.top(), min(desired.y(), area.bottom() - window.height() + 1))
        window.move(x, y)
        if not window.isVisible():
            window.show()

    def hide(self):
        self.bubble.hide()
        self.toy.hide()

    def clear(self):
        self.feedback = None
        self.hide()

    def show_feedback(self, view, text):
        self.feedback = (view.session_id, text, view.session_elapsed_ms + 1800)

    def update(self, view, visible=True, paused=False):
        if self.feedback is not None:
            session_id, _, until = self.feedback
            if view.session_id != session_id or view.session_elapsed_ms >= until or view.mode == "none":
                self.feedback = None
        screens = self.screen_rects()
        if not visible or paused or not screens or view.mode == "none":
            self.hide()
            return
        text = self.feedback[1] if self.feedback is not None else view.bubble
        if not text and view.mode in ("teaser", "teaser_swipe") and view.session_elapsed_ms < 4000:
            text = "移动鼠标逗安安，点我拍一下"
        if not text and view.mode == "satisfied" and view.phase_elapsed_ms < 1800:
            text = "喵～吃饱啦 ♡"
        if text:
            effect = "♡" if view.mode == "satisfied" else "♪"
            elapsed = view.phase_elapsed_ms if view.mode == "satisfied" else view.session_elapsed_ms
            signature = text, effect, elapsed // 60
            if self.bubble.content_signature != signature:
                self.bubble.content_signature = signature
                self.bubble.text = text
                self.bubble.effect = effect
                self.bubble.effect_ms = elapsed // 60 * 60
                width = min(340, QFontMetrics(self.bubble.font).horizontalAdvance(text) + 28)
                self.bubble.resize(width, 80)
                self.bubble.update()
            position = self.parent.pos() + QPoint((self.parent.width() - self.bubble.width()) // 2, -82)
            self._place(self.bubble, position, screens)
        else:
            self.bubble.hide()
        if view.mode in ("teaser", "teaser_swipe") and view.toy_position is not None:
            # 棒尖在指针附近偏移，保留系统指针；逻辑目标仍使用真实鼠标坐标。
            position = QPoint(round(view.toy_position[0]) + 12, round(view.toy_position[1]) + 12)
            self._place(self.toy, position, screens)
        else:
            self.toy.hide()

    @staticmethod
    def signature(view):
        falling = min(650, view.phase_elapsed_ms) // 20 if view.mode == "serving" else 0
        return view.mode, view.food, view.bowl_level, falling

    def compose(self, cat, view):
        if view.mode not in ("serving", "eating", "satisfied"):
            return cat
        result = QPixmap(cat.size())
        result.fill(Qt.GlobalColor.transparent)
        painter = QPainter(result)
        painter.drawPixmap(0, 0, self.images["bowl_back"])
        if view.bowl_level and view.food:
            offset = horizontal = 0
            if view.mode == "serving":
                progress = min(1.0, view.phase_elapsed_ms / 650)
                offset = round(-54 * (1 - progress * progress))
                horizontal = round(85 * (1 - progress))
            painter.drawPixmap(horizontal, offset, self.images[f"{view.food}-{view.bowl_level}"])
        painter.drawPixmap(0, 0, cat)
        painter.drawPixmap(0, 0, self.images["bowl_front"])
        painter.end()
        return result
