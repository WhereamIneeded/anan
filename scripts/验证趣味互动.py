"""驱动真实窗口导出趣味玩法预览与压力记录，仅捕获本程序的自有窗口。"""

import argparse
import hashlib
import json
import math
import os
import platform
import random
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

os.environ['QT_QPA_PLATFORM'] = 'windows' if any(arg in sys.argv for arg in ('--native-runtime', '--native-input')) else 'offscreen'
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from PIL import Image
from PySide6.QtCore import QPoint, QRect, Qt, QTimer, qVersion
from PySide6.QtGui import QColor, QCursor, QFont, QFontDatabase, QImage, QPainter
from PySide6.QtWidgets import QApplication, QPushButton, QWidget

from anan_pet.animation import resource_root
from anan_pet.behavior import BehaviorController
from anan_pet.play import PlayController, load_play_config
from anan_pet.window import PetWindow


def pillow(image):
    rgba = image.convertToFormat(QImage.Format.Format_RGBA8888)
    pixels = bytes(rgba.constBits())
    width = rgba.width() * 4
    rows = [pixels[y * rgba.bytesPerLine():y * rgba.bytesPerLine() + width] for y in range(rgba.height())]
    return Image.frombytes('RGBA', (rgba.width(), rgba.height()), b''.join(rows))


def decorations(window):
    return [child for child in window.findChildren(QWidget) if child.objectName().startswith('anan-play-')]


def widget_image(widget):
    image = QImage(widget.size(), QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor(0, 0, 0, 0))
    widget.render(image)
    return image


def capture(window, color='#edf1f4', width=560, height=440):
    viewport = QRect(window.x() - 120, window.y() - 100, width, height)
    image = QImage(viewport.size(), QImage.Format.Format_RGB32)
    image.fill(QColor(color))
    layers = [(window.geometry(), widget_image(window))]
    layers += [(child.geometry(), widget_image(child)) for child in decorations(window) if child.isVisible()]
    painter = QPainter(image)
    for geometry, layer in layers:
        painter.drawImage(geometry.x() - viewport.x(), geometry.y() - viewport.y(), layer)
    painter.end()
    return image


def reset(window, clock):
    window.end_play('预览复位')
    clock[0] = 0
    window.play = PlayController(load_play_config(resource_root()), random.Random(0))
    window.controller = BehaviorController({key: value.total_ms for key, value in window.clips.items()}, random.Random(0))
    window.controller.next_action = 1_000_000_000
    window.previous_advance_ms = 0
    window.preferences['sound_enabled'] = False
    window.preferences['auto_beg'] = False
    window.set_size(256)
    window.move(220, 220)
    window.transition_source = None
    window.frame_signature = None


def preview(window, clock, action, title, total, output):
    reset(window, clock)
    window.start_play(action)
    pictures, modes, unique, counts = [], [], set(), []
    swipe_done = False
    for now in range(0, total + 1, 80):
        clock[0] = now
        center = window.geometry().center()
        if action == 'teaser':
            cursor = center + QPoint(round(199 * math.sin(now / 1000)), round(-45 + 100 * math.cos(now / 1000)))
        else:
            cursor = QPoint(5, 5)
        with patch('anan_pet.window.QCursor.pos', return_value=cursor):
            window.advance()
            if action == 'teaser' and now >= 2000 and not swipe_done:
                window.play.click(now)
                swipe_done = True
                window.advance()
        QApplication.processEvents()
        frame = pillow(capture(window))
        pictures.append(frame)
        unique.add(hashlib.sha256(frame.tobytes()).digest())
        modes.append(window.play.mode.value)
        counts.append(sum(child.isVisible() for child in decorations(window)))
        if action == 'feed' and window.play.mode == 'none' and now > 1000:
            break
    destination = output / (title + '.gif')
    pictures[0].save(destination, save_all=True, append_images=pictures[1:], duration=80, loop=0, disposal=2, optimize=False)
    if action == 'feed':
        assert modes[-1] == 'none', '完整进食未按时退出'
    else:
        assert window.play.mode != 'none', '长玩法不应因短暂停顿自行退出'
    assert max(counts) <= 2, '装饰窗口数量超出上限'
    result = {'预览': destination.name, '采样毫秒': 80, '实际时长毫秒': now, '状态顺序': list(dict.fromkeys(modes)), '不同画面数': len(unique), '最大可见装饰窗口': max(counts)}
    window.end_play('预览结束')
    assert not any(child.isVisible() for child in decorations(window)), '结束后装饰残留'
    return result


def stress(window, clock):
    reset(window, clock)
    window.start_play('beg')
    original_count = len(decorations(window))
    for now in range(0, 1_200_001, 1000):
        clock[0] = now
        with patch('anan_pet.window.QCursor.pos', return_value=QPoint(5, 5)):
            window.advance()
        if now % 20000 == 0:
            QApplication.processEvents()
        assert window.play.mode == 'begging', '索食被普通调度提前终止'
        assert len(decorations(window)) == original_count, '长期索食创建了额外窗口'
    for number in range(100):
        clock[0] += 100
        window.start_play('teaser')
        window.advance()
        assert len(decorations(window)) == original_count
    window.end_play('压力测试结束')
    return {'说明': '虚拟时钟推进，不代表真实桌面三十分钟人工验收。', '索食虚拟毫秒': 1200000, '重复召唤次数': 100, '装饰窗口数量': original_count, '结束后无可见装饰': not any(child.isVisible() for child in decorations(window))}


def size_sheet(window, clock, output):
    reset(window, clock)
    window.start_play('feed')
    for now in range(0, 4501, 100):
        clock[0] = now
        window.advance()
    sheet = QImage(800, 450, QImage.Format.Format_RGB32)
    sheet.fill(QColor('#edf1f4'))
    painter = QPainter(sheet)
    painter.setFont(QApplication.font())
    painter.setPen(QColor('#223344'))
    x = 10
    for size in (100, 220, 400):
        window.set_size(size)
        window.refresh_frame(clock[0])
        painter.drawText(x, 20, f'{size} 像素')
        painter.drawImage(x, 40, widget_image(window))
        assert window.width() == size and window.height() == size
        x += size + 20
    painter.end()
    sheet.save(str(output / '进食大小对照.png'))
    window.end_play('大小预览结束')


def interaction_sheets(window, clock, output):
    sheet = QImage(1600, 2200, QImage.Format.Format_RGB32)
    sheet.fill(QColor('#edf1f4'))
    painter = QPainter(sheet)
    cases = [('索食', 'beg', 'begging'), ('投放', 'feed', 'serving'),
             ('进食', 'feed', 'eating'), ('满足', 'feed', 'satisfied'), ('逗猫', 'teaser', 'teaser')]
    for row, (title, action, mode) in enumerate(cases):
        reset(window, clock)
        window.start_play(action)
        for now in range(0, 30001, 100):
            clock[0] = now
            window.advance()
            if window.play.mode == mode and window.play.view.phase_elapsed_ms >= 400:
                break
        assert window.play.mode == mode, f'没有找到用于对照的{title}画面'
        for column, color in enumerate(('#edf1f4', '#263344')):
            painter.fillRect(column * 800, row * 440, 800, 440, QColor(color))
            painter.setPen(QColor('#223344' if column == 0 else '#f5eadc'))
            painter.drawText(column * 800 + 10, row * 440 + 20, title + '：100 / 220 / 400 像素')
            x = column * 800 + 10
            for size in (100, 220, 400):
                window.set_size(size)
                window.refresh_frame(clock[0])
                painter.drawImage(x, row * 440 + 35, widget_image(window))
                x += size + 20
    painter.end()
    sheet.save(str(output / '玩法深浅背景对照.png'))
    reset(window, clock)
    images = []
    for cancel_at in (500, 4500):
        reset(window, clock)
        window.start_play('feed')
        for now in range(0, cancel_at + 1, 100):
            clock[0] = now
            window.advance()
        images.append(pillow(capture(window)))
        window.end_play('取消预览')
        clock[0] += 500
        window.advance()
        assert window.play.mode == 'none' and not any(child.isVisible() for child in decorations(window))
        images.append(pillow(capture(window)))
    canvas = Image.new('RGB', (1120, 880), '#edf1f4')
    for index, image in enumerate(images):
        canvas.paste(image, ((index % 2) * 560, (index // 2) * 440))
    canvas.save(output / '喂食取消前后.png')
    return {'大小': [100, 220, 400], '背景': ['浅', '深'], '阶段': [case[0] for case in cases],
            '取消毫秒': [500, 4500], '取消后无可见装饰': True}


def native_runtime(app, output, seconds):
    """用真实定时器观察自身资源，不显示测试宠物或拦截用户输入。"""
    import ctypes
    from ctypes import wintypes

    class Counters(ctypes.Structure):
        _fields_ = [('cb', wintypes.DWORD), ('PageFaultCount', wintypes.DWORD)] + [(name, ctypes.c_size_t) for name in (
            'PeakWorkingSetSize', 'WorkingSetSize', 'QuotaPeakPagedPoolUsage', 'QuotaPagedPoolUsage',
            'QuotaPeakNonPagedPoolUsage', 'QuotaNonPagedPoolUsage', 'PagefileUsage', 'PeakPagefileUsage')]

    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    handle = kernel.GetCurrentProcess()
    psapi = ctypes.WinDLL('psapi', use_last_error=True)
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
    psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
    user = ctypes.WinDLL('user32', use_last_error=True)
    user.GetGuiResources.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    user.GetGuiResources.restype = wintypes.DWORD

    class CheckWindow(PetWindow):
        def show(self):
            self.setWindowOpacity(0)
            self.setWindowFlag(Qt.WindowType.WindowTransparentForInput, True)
            self.setWindowFlag(Qt.WindowType.WindowDoesNotAcceptFocus, True)
            super().show()

    temporary = tempfile.TemporaryDirectory(prefix='原生长时检查-', dir=Path(__file__).resolve().parents[1] / 'build')
    window = CheckWindow(Path(temporary.name) / '偏好.json')
    window.tray.hide()
    window.preferences['sound_enabled'] = False
    window.preferences['auto_beg'] = False
    for child in decorations(window):
        child.setWindowOpacity(0)
    window.start_play('beg')
    started = time.monotonic()
    initial_count = len(decorations(window))
    samples = []
    errors = []
    stage = ['索食']
    last_sample = [-30.0]
    split = max(10, seconds - 60)
    timer = QTimer(window)
    timer.setInterval(1000)

    def save(finished=False):
        record = {
            '说明': 'Windows原生Qt真实定时器自动检查；测试窗口视觉隐藏并穿透输入，不替代人工观感或真实点击验收。',
            '平台': app.platformName(), '计划秒数': seconds, '实际秒数': round(time.monotonic() - started, 2),
            '完成': finished, '错误': errors, '样本': samples,
        }
        (output / '原生长时验证.json').write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    def observe():
        try:
            elapsed = time.monotonic() - started
            assert len(decorations(window)) == initial_count == 2, '装饰窗口数量增长'
            if stage[0] == '索食':
                assert window.play.mode == 'begging', '索食被普通调度提前中止'
                if elapsed >= split:
                    for _ in range(100):
                        window.start_play('teaser')
                    window.start_play('feed')
                    stage[0] = '进食'
            elif stage[0] == '进食' and elapsed >= split + 35:
                assert window.play.mode == 'none', '完整进食没有按时结束'
                window.start_play('teaser')
                stage[0] = '逗猫'
            elif stage[0] == '逗猫':
                assert window.play.mode in ('teaser', 'teaser_swipe'), '逗猫状态意外退出'
            if elapsed - last_sample[0] >= 30 or elapsed >= seconds:
                memory = Counters()
                memory.cb = ctypes.sizeof(memory)
                if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(memory), memory.cb):
                    raise ctypes.WinError(ctypes.get_last_error())
                samples.append({'秒': round(elapsed, 2), '阶段': stage[0], '模式': window.play.mode.value,
                                '工作集字节': memory.WorkingSetSize, '提交字节': memory.PagefileUsage,
                                'GDI对象': user.GetGuiResources(handle, 0), 'USER对象': user.GetGuiResources(handle, 1),
                                '装饰窗口': len(decorations(window))})
                last_sample[0] = elapsed
                save()
            if elapsed >= seconds:
                timer.stop()
                window.end_play('原生长时检查完成')
                assert not any(child.isVisible() for child in decorations(window)), '结束后装饰未清理'
                save(True)
                app.quit()
        except Exception as error:
            errors.append(str(error))
            save()
            timer.stop()
            app.quit()

    timer.timeout.connect(observe)
    timer.start()
    save()
    app.exec()
    window.tray.hide()
    window.close()
    temporary.cleanup()
    if errors:
        raise RuntimeError('原生长时检查失败：' + '; '.join(errors))
    print('原生长时检查完成，结果已保存。')


def native_input(app, output):
    """只点击本脚本自己的按钮，验证真实装饰窗的穿透与不激活。"""
    import ctypes
    from ctypes import wintypes
    from PySide6.QtTest import QTest

    user = ctypes.WinDLL('user32', use_last_error=True)
    user.GetForegroundWindow.restype = wintypes.HWND
    user.WindowFromPoint.argtypes = [wintypes.POINT]
    user.WindowFromPoint.restype = wintypes.HWND
    user.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user.GetAncestor.restype = wintypes.HWND
    user.mouse_event.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t]
    saved_cursor, foreground = QCursor.pos(), user.GetForegroundWindow()
    helper = QWidget()
    helper.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus)
    helper.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    helper.resize(160, 110)
    area = app.primaryScreen().availableGeometry()
    helper.move(area.left() + 30, area.top() + 30)
    button = QPushButton('本程序穿透检查', helper)
    button.setGeometry(helper.rect())
    button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    clicks = []
    button.clicked.connect(lambda: clicks.append(True))
    helper.show()
    window = None
    results = []
    try:
        with tempfile.TemporaryDirectory(prefix='输入穿透检查-') as temporary:
            window = PetWindow(Path(temporary) / '偏好.json')
            window.timer.stop()
            window.tray.hide()
            window.hide()
            for decoration in (window.props.bubble, window.props.toy):
                decoration.text = '输入穿透检查'
                decoration.resize(100, 90)
                decoration.move(helper.pos() + QPoint(30, 10))
                decoration.show()
                decoration.raise_()
                point = decoration.geometry().center()
                QCursor.setPos(point)
                QTest.qWait(100)
                # 使用原生物理坐标查询，避免混合DPI下误把逻辑坐标当屏幕像素。
                physical = wintypes.POINT()
                if not user.GetCursorPos(ctypes.byref(physical)):
                    raise ctypes.WinError(ctypes.get_last_error())
                hit = user.WindowFromPoint(physical)
                assert user.GetAncestor(hit, 2) == int(helper.winId()), '装饰窗拦截了原生鼠标命中'
                before = len(clicks)
                user.mouse_event(0x0002, 0, 0, 0, 0)
                user.mouse_event(0x0004, 0, 0, 0, 0)
                QTest.qWait(100)
                assert len(clicks) == before + 1, '装饰覆盖时自有按钮未收到真实点击'
                assert user.GetForegroundWindow() == foreground, '检查期间焦点发生变化'
                results.append({'装饰': decoration.objectName(), '原生点击穿透': True, '未抢焦点': True})
                decoration.hide()
            window.close()
            window = None
    finally:
        QCursor.setPos(saved_cursor)
        if window is not None:
            window.tray.hide()
            window.close()
        helper.close()
    record = {'说明': 'Windows原生窗口及鼠标点击，仅点击自有辅助按钮；不替代用户在其他软件、真实多屏上的体验验收。', '结果': results}
    (output / '原生输入验证.json').write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(record, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--native-runtime', action='store_true', help='使用原生Windows真实定时器做视觉隐藏的长时检查')
    parser.add_argument('--native-input', action='store_true', help='用自有按钮检查原生装饰窗的点击穿透和焦点')
    parser.add_argument('--runtime-seconds', type=int, default=1800)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    if args.native_input:
        native_input(app, args.output)
        return
    if args.native_runtime:
        if args.runtime_seconds < 60:
            parser.error('原生运行检查至少60秒，以便完成全部进食阶段。')
        native_runtime(app, args.output, args.runtime_seconds)
        return
    font_path = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts/msyh.ttc'
    if font_path.is_file():
        font_id = QFontDatabase.addApplicationFont(str(font_path))
        families = QFontDatabase.applicationFontFamilies(font_id)
        if families:
            app.setFont(QFont(families[0], 10))
    with tempfile.TemporaryDirectory(prefix='趣味窗口预览-', dir=Path(__file__).resolve().parents[1] / 'build') as temporary:
        window = PetWindow(Path(temporary) / '偏好.json')
        window.timer.stop()
        window.tray.hide()
        clock = [0]
        window.now = lambda: clock[0]
        try:
            assert hasattr(window, 'start_play'), '尚未完成趣味窗口接线'
            records = {
                '环境': {'Python': platform.python_version(), 'Qt': qVersion(), '平台': app.platformName()},
                '说明': '使用真实PetWindow和自有装饰窗口绘制；临时偏好、默认静音、可控时钟，未捕获其他应用或用户桌面。',
                '索食': preview(window, clock, 'beg', '持续撒娇索食', 12000, args.output),
                '喂食': preview(window, clock, 'feed', '猫碗完整进食', 30000, args.output),
                '逗猫': preview(window, clock, 'teaser', '逗猫棒互动', 9000, args.output),
                '压力检查': stress(window, clock),
            }
            size_sheet(window, clock, args.output)
            records['画面对照'] = interaction_sheets(window, clock, args.output)
            (args.output / '窗口验证记录.json').write_text(json.dumps(records, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            print(json.dumps(records, ensure_ascii=False, indent=2))
        finally:
            if hasattr(window, 'end_play'):
                window.end_play('预览清理')
            window.tray.hide()
            window.close()


if __name__ == '__main__':
    main()
