"""全局双击退出接线只影响当前逗猫会话。"""

import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication
from anan_pet.window import PetWindow


@pytest.fixture
def pet(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    w = PetWindow(tmp_path / '偏好.json')
    w.timer.stop()
    clock = [0]
    monkeypatch.setattr(w, 'now', lambda: clock[0])
    monkeypatch.setattr('anan_pet.window.QCursor.pos', lambda: QPoint(5000, 5000))
    yield w, clock
    if w.dialog is not None:
        w.dialog.close()
    w.tray.hide()
    w.close()


def test_global_exit_cancels_teaser_and_clears_its_decoration(pet):
    w = pet[0]
    w.start_play('teaser')
    assert hasattr(w, 'teaser_exit'), '尚未连接全局双击退出'
    monitor = w.teaser_exit
    assert monitor.enabled
    w.handle_teaser_double_click(monitor.generation)
    assert w.play.mode == 'none'
    assert not monitor.enabled
    assert not w.props.toy.isVisible() and not w.props.bubble.isVisible()


def test_old_signal_cannot_cancel_a_restarted_teaser(pet):
    w = pet[0]
    w.start_play('teaser')
    assert hasattr(w, 'teaser_exit')
    old = w.teaser_exit.generation
    w.start_play('teaser')
    assert w.teaser_exit.generation != old
    w.handle_teaser_double_click(old)
    assert w.play.mode == 'teaser'
    w.play.click(0)
    assert w.play.mode == 'teaser_swipe'
    w.handle_teaser_double_click(w.teaser_exit.generation)
    assert w.play.mode == 'none'


@pytest.mark.parametrize('operation', ['menu', 'size', 'hide', 'close', 'end', 'scratch', 'feed', 'beg'])
def test_pauses_or_other_actions_disable_monitor_and_ignore_queued_event(pet, operation):
    w = pet[0]
    w.start_play('teaser')
    assert hasattr(w, 'teaser_exit')
    monitor = w.teaser_exit
    old = monitor.generation
    if operation == 'menu':
        w.set_menu_open(True)
    elif operation == 'size':
        w.size_dialog()
    elif operation in ('hide', 'close'):
        getattr(w, operation)()
    elif operation == 'end':
        w.end_play()
    elif operation == 'scratch':
        w.act('scratch')
    else:
        w.start_play(operation)
    expected = w.play.mode
    assert not monitor.enabled
    w.handle_teaser_double_click(old)
    assert w.play.mode == expected


def test_pause_resume_starts_a_fresh_click_history(pet):
    w = pet[0]
    w.start_play('teaser')
    assert hasattr(w, 'teaser_exit')
    old = w.teaser_exit.generation
    w.set_menu_open(True)
    w.set_menu_open(False)
    assert w.teaser_exit.enabled and w.teaser_exit.generation != old
    w.handle_teaser_double_click(old)
    assert w.play.mode == 'teaser'


def test_pending_waking_teaser_can_be_cancelled(pet):
    w, clock = pet
    w.act('sleep')
    w.start_play('teaser')
    assert w.pending_play is not None
    assert hasattr(w, 'teaser_exit')
    w.handle_teaser_double_click(w.teaser_exit.generation)
    assert w.pending_play is None
    for now in range(1000, 9001, 1000):
        clock[0] = now
        w.advance()
    assert w.play.mode == 'none'


def test_teaser_hint_explains_both_actions(pet):
    w = pet[0]
    w.start_play('teaser')
    assert '拍棒' in w.props.bubble.text
    assert '双击别处收起' in w.props.bubble.text
