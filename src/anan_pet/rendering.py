"""稳定静止躯干，并在预乘透明度空间中衔接相邻姿势。"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPixmap, QRadialGradient

from .animation import GROUND_ANCHOR


def align_pixmap(pixmap, anchor):
    """按动作的落地点对齐整张姿态，不重新缩放或截取身体。"""
    if anchor == GROUND_ANCHOR:
        return pixmap
    result = QPixmap(pixmap.size())
    result.fill(Qt.GlobalColor.transparent)
    painter = QPainter(result)
    painter.drawPixmap(GROUND_ANCHOR[0] - anchor[0], GROUND_ANCHOR[1] - anchor[1], pixmap)
    painter.end()
    return result


def remove_green_spill(pixmap):
    """安安没有绿色毛发，只压低绿幕溢色，保留原始轮廓和透明度。"""
    source = pixmap.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
    pixels = bytearray(source.constBits())
    for y in range(source.height()):
        start = y * source.bytesPerLine()
        for offset in range(start, start + source.width() * 4, 4):
            if pixels[offset + 3]:
                ceiling = max(pixels[offset], pixels[offset + 2])
                if pixels[offset + 1] > ceiling:
                    pixels[offset + 1] = ceiling
    cleaned = QImage(pixels, source.width(), source.height(), source.bytesPerLine(), QImage.Format.Format_RGBA8888).copy()
    cleaned.setDevicePixelRatio(source.devicePixelRatio())
    return QPixmap.fromImage(cleaned)


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


def stabilize_idle(pixmaps, eyes, radius):
    mask = QImage(pixmaps[0].size(), QImage.Format.Format_ARGB32_Premultiplied)
    mask.fill(Qt.GlobalColor.transparent)
    painter = QPainter(mask)
    for x, y in eyes:
        gradient = QRadialGradient(x, y, radius)
        gradient.setColorAt(0, QColor(255, 255, 255, 255))
        gradient.setColorAt(0.65, QColor(255, 255, 255, 255))
        gradient.setColorAt(1, QColor(255, 255, 255, 0))
        painter.setBrush(gradient)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(x - radius, y - radius, radius * 2, radius * 2)
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


def stabilize_look(pixmaps, base, head_bottom, body_top):
    mask = QImage(base.size(), QImage.Format.Format_ARGB32_Premultiplied)
    mask.fill(Qt.GlobalColor.transparent)
    gradient = QLinearGradient(0, head_bottom, 0, body_top)
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


def keep_static_body(pixmap, base, top=128):
    # 半透明毛尖混合时会有舍入误差；静止身体直接复用原像素。
    result = pixmap.copy()
    painter = QPainter(result)
    painter.setClipRect(0, top, base.width(), base.height() - top)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
    painter.drawPixmap(0, 0, base)
    painter.end()
    return result
