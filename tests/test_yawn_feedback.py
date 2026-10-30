"""验证普通哈欠的短文字时段、打断清理和趣味会话优先级。"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from anan_pet.window import PetWindow


@pytest.fixture
def scene(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    clock = [0]
    monkeypatch.setattr("anan_pet.window.QCursor.pos", lambda: QPoint(5000, 5000))
    window = PetWindow(tmp_path / "偏好.json")
    window.timer.stop()
    window.move(100, 100)
    window.controller.next_action = 100000
    monkeypatch.setattr(window, "now", lambda: clock[0])
    yield window, clock
    if window.dialog is not None:
        window.dialog.close()
    window.menu.close()
    window.tray.hide()
    window.close()


def step(scene, now):
    scene[1][0] = now
    scene[0].advance()
    return scene[0]


def open_mouth(scene):
    window = scene[0]
    window.act("yawn")
    step(scene, scene[1][0] + 400)
    assert window.controller.state == "yawn"
    assert window.props.bubble.isVisible(), "张嘴时应显示哈欠短文字"
    assert window.props.bubble.text == "嗷呜～"
    return window


def test_manual_yawn_only_shows_short_text_during_open_mouth(scene):
    window = scene[0]
    window.act("yawn")
    assert not window.props.bubble.isVisible()
    step(scene, 399)
    assert not window.props.bubble.isVisible()
    step(scene, 400)
    assert window.props.bubble.isVisible(), "400毫秒张嘴时应显示哈欠短文字"
    assert window.props.bubble.text == "嗷呜～"
    step(scene, 1049)
    assert window.props.bubble.isVisible()
    step(scene, 1050)
    assert not window.props.bubble.isVisible()
    step(scene, window.clips["yawn"].total_ms)
    assert window.controller.state == "idle"
    assert not window.props.bubble.isVisible()


def test_scheduled_yawn_uses_actual_start_time_without_manual_action(scene, monkeypatch):
    window = scene[0]
    window.controller.next_action = 1000
    monkeypatch.setattr(window.controller, "choose_action", lambda now: "yawn")
    step(scene, 1000)
    assert window.controller.state == "yawn"
    assert window.controller.started == 1000
    assert not window.props.bubble.isVisible()
    step(scene, 1399)
    assert not window.props.bubble.isVisible()
    step(scene, 1400)
    assert window.props.bubble.isVisible()
    assert window.props.bubble.text == "嗷呜～"
    step(scene, 2050)
    assert not window.props.bubble.isVisible()


def test_queued_yawn_waits_for_actual_action_instead_of_request_time(scene):
    window = scene[0]
    window.act("sleep")
    step(scene, window.clips["prone_enter"].total_ms)
    assert window.controller.state == "prone_sleep"
    window.act("yawn")
    step(scene, scene[1][0] + 400)
    assert window.controller.state == "prone_exit"
    assert not window.props.bubble.isVisible()
    step(scene, scene[1][0] + window.clips["prone_exit"].total_ms)
    assert window.controller.state == "yawn"
    assert not window.props.bubble.isVisible()
    step(scene, scene[1][0] + 400)
    assert window.props.bubble.isVisible()
    assert window.props.bubble.text == "嗷呜～"


def test_repeated_updates_neither_extend_text_nor_repaint_static_bubble(scene, monkeypatch):
    window = open_mouth(scene)
    requests = []
    monkeypatch.setattr(window.props.bubble, "update", lambda: requests.append(1))
    for now in (400, 400, 416, 432, 500, 800, 1049):
        step(scene, now)
        assert window.props.bubble.isVisible()
    assert requests == [], "固定短文字不应每16毫秒请求重绘"
    step(scene, 1050)
    assert not window.props.bubble.isVisible()
    for now in (1050, 1066, 1200):
        step(scene, now)
        assert not window.props.bubble.isVisible(), "重复刷新不能续期或补发"


def test_next_yawn_has_its_own_short_text_window(scene):
    window = open_mouth(scene)
    step(scene, window.clips["yawn"].total_ms)
    assert window.controller.state == "idle"
    assert not window.props.bubble.isVisible()
    open_mouth(scene)
    step(scene, window.controller.started + 1050)
    assert not window.props.bubble.isVisible()


@pytest.mark.parametrize("action", ["click", "waving", "sleep", "supine", "drag_start", "wake"])
def test_other_action_immediately_clears_yawn_text(scene, action):
    window = open_mouth(scene)
    window.act(action)
    assert window.controller.state != "yawn"
    assert not window.props.bubble.isVisible()
    step(scene, 600)
    assert not window.props.bubble.isVisible()


@pytest.mark.parametrize("operation", ["hide", "close", "quit"])
def test_hiding_or_exiting_clears_yawn_text(scene, operation):
    window = open_mouth(scene)
    getattr(window, operation)()
    assert not window.props.bubble.isVisible()
    step(scene, 600)
    assert not window.props.bubble.isVisible()
    if operation == "hide":
        step(scene, 1200)
        window.show_pet()
        assert not window.props.bubble.isVisible(), "恢复显示不能补发过期的哈欠文字"


@pytest.mark.parametrize("control", ["menu", "dialog"])
def test_controls_hide_text_and_resume_only_inside_original_time_window(scene, control):
    window = open_mouth(scene)
    if control == "menu":
        window.menu.popup(window.geometry().center())
    else:
        window.size_dialog()
    assert not window.props.bubble.isVisible()
    step(scene, 700)
    assert not window.props.bubble.isVisible()
    if control == "menu":
        window.menu.close()
    else:
        window.dialog.close()
    assert window.props.bubble.isVisible()
    assert window.props.bubble.text == "嗷呜～"
    step(scene, 1050)
    assert not window.props.bubble.isVisible(), "关闭控件不能延长动作原定的文字时段"


@pytest.mark.parametrize("kind, text", [("beg", "冻干"), ("feed", None), ("teaser", "点我拍棒；双击别处收起")])
def test_play_session_owns_the_existing_bubble_without_yawn_residue(scene, kind, text):
    window = open_mouth(scene)
    bubble = window.props.bubble
    window.start_play(kind)
    # 即使普通控制器仍是哈欠，真正播放的趣味会话也必须优先。
    window.controller.handle("yawn", scene[1][0])
    step(scene, 800)
    assert window.props.bubble is bubble
    assert bubble.isVisible() == (text is not None)
    if text is not None:
        assert text in bubble.text
        assert bubble.text != "嗷呜～"
    decorations = [item for item in window.findChildren(QWidget) if item.objectName().startswith("anan-play-")]
    assert len(decorations) == 2


def test_yawn_keeps_default_silence_and_uses_existing_timer(scene):
    window = scene[0]
    timers = window.findChildren(QTimer)
    assert not window.preferences["sound_enabled"]
    open_mouth(scene)
    assert window.findChildren(QTimer) == timers
    assert len(timers) == 1


def test_drag_release_after_yawn_does_not_jump_or_leave_text(scene):
    window = open_mouth(scene)
    QTest.mousePress(window, Qt.MouseButton.LeftButton, pos=QPoint(50, 50))
    QTest.mouseMove(window, QPoint(100, 50))
    QTest.mouseRelease(window, Qt.MouseButton.LeftButton, pos=QPoint(100, 50))
    assert window.controller.state == "idle"
    assert not window.controller.dragging
    assert not window.props.bubble.isVisible()
