"""稳定静止躯干，并在预乘透明度空间中衔接相邻姿势。"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPixmap, QRadialGradient


def blend_pixmaps(left, right, amount):
    if amount <= 0:
        return left
    if amount >= 1:
        return right
    result = QImage(left.size(), QImage.Format.Format_ARGB32_Premultiplied)
    result.fill(Qt.GlobalColor.transparent)
    painter = QPainter(result)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
    for source, weight in ((left, 1 - amount), (right, amount)):
        # 先独立预乘再相加，避免重叠身体在过渡中变成半透明。
        layer = QImage(left.size(), QImage.Format.Format_ARGB32_Premultiplied)
        layer.fill(Qt.GlobalColor.transparent)
        layer_painter = QPainter(layer)
        layer_painter.setOpacity(weight)
        layer_painter.drawPixmap(0, 0, source)
        layer_painter.end()
        painter.drawImage(0, 0, layer)
    painter.end()
    return QPixmap.fromImage(result)


def stabilize_idle(pixmaps):
    mask = QImage(pixmaps[0].size(), QImage.Format.Format_ARGB32_Premultiplied)
    mask.fill(Qt.GlobalColor.transparent)
    painter = QPainter(mask)
    for x in (108, 137):
        gradient = QRadialGradient(x, 106, 14)
        gradient.setColorAt(0, QColor(255, 255, 255, 255))
        gradient.setColorAt(0.65, QColor(255, 255, 255, 255))
        gradient.setColorAt(1, QColor(255, 255, 255, 0))
        painter.setBrush(gradient)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(x - 14, 92, 28, 28)
    painter.end()
    result = []
    for pixmap in pixmaps:
        eyes = pixmap.toImage().convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
        painter = QPainter(eyes)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
        painter.drawImage(0, 0, mask)
        painter.end()
        stable = pixmaps[0].copy()
        painter = QPainter(stable)
        painter.drawImage(0, 0, eyes)
        painter.end()
        result.append(stable)
    return result


def stabilize_look(pixmaps, base):
    mask = QImage(base.size(), QImage.Format.Format_ARGB32_Premultiplied)
    mask.fill(Qt.GlobalColor.transparent)
    gradient = QLinearGradient(0, 118, 0, 128)
    gradient.setColorAt(0, QColor(255, 255, 255, 255))
    gradient.setColorAt(1, QColor(255, 255, 255, 0))
    painter = QPainter(mask)
    painter.fillRect(mask.rect(), gradient)
    painter.end()
    result = []
    for pixmap in pixmaps:
        body = base.toImage()
        painter = QPainter(body)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationOut)
        painter.drawImage(0, 0, mask)
        painter.end()
        head = pixmap.toImage()
        painter = QPainter(head)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
        painter.drawImage(0, 0, mask)
        painter.end()
        painter = QPainter(body)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
        painter.drawImage(0, 0, head)
        painter.end()
        result.append(QPixmap.fromImage(body))
    return result


def keep_static_body(pixmap, base):
    # 半透明毛尖混合时会有舍入误差；静止身体直接复用原像素。
    result = pixmap.copy()
    painter = QPainter(result)
    painter.setClipRect(0, 128, base.width(), base.height() - 128)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
    painter.drawPixmap(0, 0, base)
    painter.end()
    return result
