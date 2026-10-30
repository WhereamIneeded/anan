"""真实窗口导出较长招呼、爱心动画、淡出和三种大小预览。"""

import argparse
import json
import os
from pathlib import Path
import tempfile
from unittest.mock import patch

from 验证趣味互动 import capture, decorations, pillow, reset
from PySide6.QtCore import QPoint
from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage, QPainter
from PySide6.QtWidgets import QApplication
from anan_pet.window import PetWindow


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    root = Path(__file__).resolve().parents[1]
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    font_id = QFontDatabase.addApplicationFont(str(Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts/msyh.ttc'))
    families = QFontDatabase.applicationFontFamilies(font_id)
    # 离屏字体库需要显式加入符号回退，避免爱心显示成缺字方框。
    QFontDatabase.addApplicationFont(str(Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts/seguisym.ttf'))
    if families:
        app.setFont(QFont(families[0], 10))
    with tempfile.TemporaryDirectory(prefix='招呼预览-', dir=root / 'build') as temporary:
        w = PetWindow(Path(temporary) / '偏好.json')
        w.timer.stop()
        w.tray.hide()
        clock = [0]
        w.now = lambda: clock[0]
        try:
            record = {'说明': '真实Qt离屏绘制，仅自有窗口；可控时钟、临时偏好、默认无声音，不代表用户桌面人工验收。', '预览': []}
            for name, color in (('浅色', '#edf1f4'), ('深色', '#263344')):
                reset(w, clock)
                w.act('waving')
                images, visible, opacity = [], [], []
                for now in range(0, 3441, 40):
                    clock[0] = now
                    with patch('anan_pet.window.QCursor.pos', return_value=QPoint(5000, 5000)):
                        w.advance()
                    QApplication.processEvents()
                    images.append(pillow(capture(w, color)))
                    if w.props.bubble.isVisible():
                        assert w.props.bubble.text == '喵～' and w.props.bubble.effect == '♡'
                        visible.append(now)
                        opacity.append(w.props.bubble.content_opacity)
                    assert len(decorations(w)) == 2
                assert w.controller.state == 'idle' and not w.props.bubble.isVisible()
                assert min(visible) == 280 and max(visible) == 2440 and min(opacity) < 1
                filename = '喵招呼-' + name + '.gif'
                images[0].save(args.output / filename, save_all=True, append_images=images[1:], duration=40, loop=0, disposal=2, optimize=False)
                record['预览'].append({'文件': filename, '动作毫秒': w.clips['waving'].total_ms, '文字采样时段': [min(visible), max(visible)], '末尾淡出': True, '结束清理': True})
            sheet = QImage(1680, 580, QImage.Format.Format_RGB32)
            sheet.fill(QColor('#edf1f4'))
            painter = QPainter(sheet)
            painter.setFont(app.font())
            for column, size in enumerate((100, 220, 400)):
                reset(w, clock)
                w.set_size(size)
                w.act('waving')
                clock[0] = 900
                w.advance()
                QApplication.processEvents()
                painter.drawText(column * 560 + 15, 25, f'{size}逻辑像素：喵招呼与爱心')
                painter.drawImage(column * 560, 35, capture(w, height=540))
            painter.end()
            sheet.save(str(args.output / '招呼大小对照.png'))
            (args.output / '招呼验证.json').write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            print(json.dumps(record, ensure_ascii=False, indent=2))
        finally:
            w.tray.hide()
            w.close()


if __name__ == '__main__':
    main()
