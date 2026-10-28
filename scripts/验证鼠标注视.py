"""通过附近鼠标感知和窗口绘制导出十六方向截图与注视预览。"""

import argparse
import json
import math
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PIL import Image
from PySide6.QtCore import QPoint
from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage, QPainter
from PySide6.QtWidgets import QApplication

from anan_pet.window import PetWindow


def capture(window, color):
    image = QImage(window.size(), QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor(0, 0, 0, 0))
    window.render(image)
    result = QImage(window.size(), QImage.Format.Format_RGB32)
    result.fill(QColor(color))
    painter = QPainter(result)
    painter.drawImage(0, 0, image)
    painter.end()
    return result


def pillow(image):
    rgba = image.convertToFormat(QImage.Format.Format_RGBA8888)
    pixels = bytes(rgba.constBits())
    rows = [pixels[y * rgba.bytesPerLine():y * rgba.bytesPerLine() + rgba.width() * 4] for y in range(rgba.height())]
    return Image.frombytes("RGBA", (rgba.width(), rgba.height()), b"".join(rows))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="预览输出目录")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    # 无界面平台可能没有默认字体，显式加载系统中文字体验证预览标签。
    font_path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts/msyh.ttc"
    if font_path.is_file():
        font_id = QFontDatabase.addApplicationFont(str(font_path))
        families = QFontDatabase.applicationFontFamilies(font_id)
        if families:
            app.setFont(QFont(families[0], 10))
    with tempfile.TemporaryDirectory(prefix="anan-look-") as folder:
        window = PetWindow(Path(folder) / "偏好.json")
        try:
            window.timer.stop()
            window.tray.hide()
            window.resize(256, 256)
            frames = []
            observed = []
            for background, name in (("#ffffff", "浅色"), ("#182034", "深色")):
                sheet = QImage(1024, 1104, QImage.Format.Format_RGB32)
                sheet.fill(QColor(background))
                painter = QPainter(sheet)
                painter.setFont(app.font())
                painter.setPen(QColor("black" if name == "浅色" else "white"))
                for direction in range(16):
                    angle = math.radians(direction * 22.5)
                    delta = QPoint(round(window.width() * math.sin(angle)), round(-window.width() * math.cos(angle)))
                    cursor = window.geometry().center() + delta
                    assert not window.geometry().contains(cursor), "十六方向预览必须使用窗口外的附近鼠标"
                    now = (direction + (0 if name == "浅色" else 16)) * 300
                    with patch("anan_pet.window.QCursor.pos", return_value=cursor):
                        window.update_attention(now)
                        window.refresh_frame(now)
                        window.refresh_frame(now + 100)
                    assert window.look_index == direction
                    image = capture(window, background)
                    x, y = direction % 4 * 256, direction // 4 * 276
                    painter.drawText(x + 8, y + 16, f"{direction} / {direction * 22.5:g}°")
                    painter.drawImage(x, y + 20, image)
                    if name == "浅色":
                        frames.append(pillow(image))
                        observed.append(window.look_index)
                        if direction in (6, 8, 9, 10):
                            image.save(str(args.output / f"低头方向-{direction}.png"))
                painter.end()
                sheet.save(str(args.output / f"十六方向-{name}.png"))
            frames[0].save(args.output / "鼠标注视.gif", save_all=True, append_images=frames[1:], duration=350, loop=0, disposal=2)
            sizes = QImage(720, 420, QImage.Format.Format_RGB32)
            sizes.fill(QColor("white"))
            painter = QPainter(sizes)
            painter.setFont(app.font())
            painter.setPen(QColor("black"))
            x = 0
            for size in (100, 220, 400):
                window.resize(size, size)
                with patch("anan_pet.window.QCursor.pos", return_value=window.geometry().center() + QPoint(round(-size * 0.38), round(size * 0.92))):
                    window.update_attention(10000 + size)
                    window.refresh_frame(10000 + size)
                    window.refresh_frame(10100 + size)
                painter.drawText(x + 5, 16, str(size))
                painter.drawImage(x, 420 - size, capture(window, "white"))
                x += size
            painter.end()
            sizes.save(str(args.output / "大小对照.png"))
            result = {"平台": app.platformName(), "画布像素": [256, 256], "实际注视方向": observed, "方向采样鼠标位于窗口外": True, "方向采样半径逻辑像素": 256, "说明": "使用临时偏好和窗口外的附近模拟鼠标，通过 update_attention、refresh_frame 与 QWidget.render 导出实际画面；不替代 Windows 桌面验收。"}
            (args.output / "验证记录.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        finally:
            window.timer.stop()
            window.tray.hide()
            window.close()
            app.processEvents()


if __name__ == "__main__":
    main()
