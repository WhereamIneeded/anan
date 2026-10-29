"""用真实Qt播放器导出体态前后对照、连续动作和哈欠文字。"""

import argparse
import json
import os
from pathlib import Path
import tempfile
from unittest.mock import patch

from 验证趣味互动 import capture, decorations, pillow, reset
from PySide6.QtCore import QPoint
from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

from anan_pet.rendering import align_pixmap, remove_green_spill
from anan_pet.window import PetWindow


ROOT = Path(__file__).resolve().parents[1]


def prepare(window, clock):
    reset(window, clock)
    window.visual_key = 'idle'
    window.visual_index = 0
    window.render_domain = None
    window.last_render_ms = None
    window.cat_frame = window.frame = window.pixmaps['idle'][0]
    window.frame_signature = None
    window.transition_source = None
    window.refresh_frame(0)


def compare(window, output):
    before = json.loads((ROOT / '制作/体态统一/基线动画配置.json').read_text(encoding='utf-8'))
    actions = [('索食', 'beg_call'), ('抬爪索食', 'beg_paw'), ('挠耳', 'scratch'), ('舔爪', 'wash'), ('哈欠', 'yawn')]
    records = []
    for color, name in (('#f9fafb', '浅色'), ('#263344', '深色')):
        sheet = QImage(840, 1540, QImage.Format.Format_RGB32)
        sheet.fill(QColor(color))
        painter = QPainter(sheet)
        painter.setFont(QApplication.font())
        painter.setPen(QColor('#263344' if name == '浅色' else '#f7f0e6'))
        for column, title in enumerate(('保留的待机', '1.3.0动作', '统一后的动作')):
            painter.drawText(column * 280 + 25, 30, title)
        for row, (title, key) in enumerate(actions):
            old = before[key]
            old_frame = align_pixmap(remove_green_spill(QPixmap(str(ROOT / 'assets' / old['frames'][0]))), tuple(old['anchor']))
            new_frame = window.pixmaps[key][0]
            for column, frame in enumerate((window.pixmaps['idle'][0], old_frame, new_frame)):
                painter.drawPixmap(column * 280 + 10, row * 300 + 45, frame)
            painter.drawText(25, row * 300 + 325, title)
            if name == '浅色':
                def dimensions(frame):
                    alpha = pillow(frame.toImage()).getchannel('A').point(lambda value: 255 if value > 128 else 0)
                    box = alpha.getbbox()
                    return {'宽': box[2] - box[0], '高': box[3] - box[1], '底边': box[3]}
                records.append({'动作': key, '待机': dimensions(window.pixmaps['idle'][0]),
                                '之前': dimensions(old_frame), '之后': dimensions(new_frame)})
        painter.end()
        sheet.save(str(output / f'体态前后对照-{name}.png'))
    return records


def transition(window, clock, action, output):
    prepare(window, clock)
    pictures, modes, bubble_times = [], [], []
    for now in range(0, 4801, 40):
        clock[0] = now
        if now == 600:
            window.start_play('beg') if action == 'beg' else window.act(action)
        if action == 'beg' and now == 4000:
            window.end_play('连续预览结束')
        with patch('anan_pet.window.QCursor.pos', return_value=QPoint(5000, 5000)):
            window.advance()
        QApplication.processEvents()
        pictures.append(pillow(capture(window)))
        modes.append(window.play.mode.value if window.play.mode != 'none' else window.controller.state)
        if window.props.bubble.isVisible() and window.props.bubble.text == '嗷呜～':
            bubble_times.append(now - 600)
        assert len(decorations(window)) == 2
    if action == 'yawn':
        assert bubble_times and min(bubble_times) == 400 and max(bubble_times) < 1050
    else:
        assert not bubble_times
    assert window.play.mode == 'none' and window.controller.state == 'idle'
    assert not any(child.isVisible() for child in decorations(window))
    title = {'beg': '待机与索食连续衔接', 'scratch': '待机与挠耳连续衔接', 'yawn': '哈欠嗷呜文字'}[action]
    pictures[0].save(output / (title + '.gif'), save_all=True, append_images=pictures[1:], duration=40, loop=0, disposal=2, optimize=False)
    return {'预览': title + '.gif', '采样毫秒': 40, '状态顺序': list(dict.fromkeys(modes)),
            '哈欠文字相对时段': [min(bubble_times), max(bubble_times)] if bubble_times else None,
            '结束后无可见装饰': True}


def sizes(window, clock, output):
    sheet = QImage(1680, 580, QImage.Format.Format_RGB32)
    sheet.fill(QColor('#edf1f4'))
    painter = QPainter(sheet)
    painter.setFont(QApplication.font())
    for column, size in enumerate((100, 220, 400)):
        prepare(window, clock)
        window.set_size(size)
        window.act('yawn')
        clock[0] = 600
        window.advance()
        QApplication.processEvents()
        assert window.props.bubble.isVisible() and window.props.bubble.text == '嗷呜～'
        painter.drawText(column * 560 + 15, 25, f'{size}逻辑像素：哈欠张嘴与文字')
        painter.drawImage(column * 560, 35, capture(window, height=540))
    painter.end()
    sheet.save(str(output / '哈欠文字大小对照.png'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    (ROOT / 'build').mkdir(exist_ok=True)
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    font_path = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts/msyh.ttc'
    if font_path.is_file():
        font_id = QFontDatabase.addApplicationFont(str(font_path))
        families = QFontDatabase.applicationFontFamilies(font_id)
        if families:
            app.setFont(QFont(families[0], 10))
    with tempfile.TemporaryDirectory(prefix='体态与哈欠验证-', dir=ROOT / 'build') as temporary:
        window = PetWindow(Path(temporary) / '偏好.json')
        window.timer.stop()
        window.tray.hide()
        clock = [0]
        window.now = lambda: clock[0]
        try:
            record = {'说明': '真实PetWindow、自有气泡和可控时钟，不截取用户桌面或外放声音；旧帧仅用于对照。',
                      '体态测量': compare(window, args.output),
                      '连续预览': [transition(window, clock, action, args.output) for action in ('beg', 'scratch', 'yawn')]}
            sizes(window, clock, args.output)
            (args.output / '验证记录.json').write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            print(json.dumps(record, ensure_ascii=False, indent=2))
        finally:
            window.tray.hide()
            window.close()


if __name__ == '__main__':
    main()
