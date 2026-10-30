"""验证较长打招呼及喵气泡、限量爱心和可靠清理。"""

import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from anan_pet.window import PetWindow


@pytest.fixture
def scene(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    clock = [0]
    w = PetWindow(tmp_path / '偏好.json')
    w.timer.stop()
    w.controller.next_action = 100000
    monkeypatch.setattr(w, 'now', lambda: clock[0])
    monkeypatch.setattr('anan_pet.window.QCursor.pos', lambda: QPoint(5000, 5000))
    yield w, clock
    if w.dialog is not None:
        w.dialog.close()
    w.tray.hide()
    w.close()


def step(scene, now):
    scene[1][0] = now
    scene[0].advance()
    return scene[0]


def test_greeting_has_two_gentle_waves_and_returns_after_2800_ms(scene):
    w = scene[0]
    clip = w.clips['waving']
    assert clip.total_ms == 2800, '打招呼仍然过短'
    assert [path.name for path in clip.frames] == ['00.png', '01.png', '02.png', '01.png', '02.png', '03.png']
    assert not clip.loop
    w.act('waving')
    for now in (300, 900, 1600, 2200, 2799):
        assert step(scene, now).controller.state == 'waving'
    assert step(scene, 2800).controller.state == 'idle'


def test_greeting_bubble_has_animated_hearts_and_fades_without_extra_windows(scene):
    w = scene[0]
    w.act('waving')
    assert not w.props.bubble.isVisible()
    step(scene, 400)
    bubble = w.props.bubble
    assert bubble.isVisible() and bubble.text == '喵～'
    assert bubble.effect == '♡'
    before = QImage(bubble.size(), QImage.Format.Format_ARGB32)
    bubble.render(before)
    step(scene, 640)
    after = QImage(bubble.size(), QImage.Format.Format_ARGB32)
    bubble.render(after)
    assert before != after, '爱心应缓缓浮动'
    assert len([c for c in w.findChildren(QWidget) if c.objectName().startswith('anan-play-')]) == 2
    step(scene, 2360)
    assert 0 < bubble.content_opacity < 1
    step(scene, 2480)
    assert not bubble.isVisible()
    assert w.controller.state == 'waving'
    step(scene, 2800)
    assert not bubble.isVisible()


def test_repeated_timestamp_does_not_repeat_effect_updates(scene, monkeypatch):
    w = scene[0]
    w.act('waving')
    step(scene, 600)
    paints = []
    monkeypatch.setattr(w.props.bubble, 'update', lambda: paints.append(True))
    for _ in range(20):
        step(scene, 600)
    assert paints == []


@pytest.mark.parametrize('interrupt', ['click', 'sleep', 'scratch', 'hide', 'close'])
def test_interruption_clears_greeting(scene, interrupt):
    w = scene[0]
    w.act('waving')
    step(scene, 500)
    assert w.props.bubble.isVisible()
    if interrupt in ('hide', 'close'):
        getattr(w, interrupt)()
    else:
        w.act(interrupt)
    assert not w.props.bubble.isVisible()


def test_drag_does_not_leave_hearts_or_jump(scene):
    w = scene[0]
    w.act('waving')
    step(scene, 500)
    QTest.mousePress(w, Qt.MouseButton.LeftButton, pos=QPoint(50, 50))
    QTest.mouseMove(w, QPoint(110, 50))
    QTest.mouseRelease(w, Qt.MouseButton.LeftButton, pos=QPoint(110, 50))
    assert w.controller.state == 'idle'
    assert not w.props.bubble.isVisible()


@pytest.mark.parametrize('pause', ['menu', 'size'])
def test_controls_hide_greeting_and_do_not_extend_original_duration(scene, pause):
    w = scene[0]
    w.act('waving')
    step(scene, 400)
    if pause == 'menu':
        w.set_menu_open(True)
    else:
        w.size_dialog()
    assert not w.props.bubble.isVisible()
    step(scene, 2600)
    if pause == 'menu':
        w.set_menu_open(False)
    else:
        w.dialog.close()
    assert not w.props.bubble.isVisible()
    assert step(scene, 2800).controller.state == 'idle'


@pytest.mark.parametrize('kind', ['beg', 'feed', 'teaser'])
def test_play_feedback_wins_over_greeting(scene, kind):
    w = scene[0]
    w.act('waving')
    step(scene, 400)
    w.start_play(kind)
    w.controller.handle('waving', 400)
    step(scene, 900)
    assert not w.props.bubble.isVisible() or w.props.bubble.text != '喵～'
    assert not w.preferences['sound_enabled']
