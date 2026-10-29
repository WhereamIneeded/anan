"""趣味会话接入真实 Qt 窗口后的输入、暂停、道具和清理回归。"""

import os
from dataclasses import replace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from anan_pet.settings import load_settings
from anan_pet.window import PetWindow


@pytest.fixture
def scene(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    clock, cursor = [0], [QPoint(5000, 5000)]
    monkeypatch.setattr("anan_pet.window.QCursor.pos", lambda: cursor[0])
    window = PetWindow(tmp_path / "偏好.json")
    window.timer.stop()
    window.move(100, 100)
    window.controller.next_action = 100000
    monkeypatch.setattr(window, "now", lambda: clock[0])
    yield window, clock, cursor
    if window.dialog is not None:
        window.dialog.close()
    window.menu.close()
    window.tray.hide()
    window.close()


def step(scene, now):
    scene[1][0] = now
    scene[0].advance()
    return scene[0]


def click(window):
    QTest.mouseClick(window, Qt.MouseButton.LeftButton, pos=QPoint(90, 100))


def decorations(window):
    return [item for item in window.findChildren(QWidget) if item.objectName().startswith("anan-play-")]


def test_old_preferences_default_to_auto_beg_and_no_sound(tmp_path):
    path = tmp_path / "旧偏好.json"
    path.write_text('{"size": 300, "quiet": true}', encoding="utf-8")
    assert load_settings(path)["auto_beg"] is True
    assert load_settings(path)["sound_enabled"] is False
    path.write_text('{"auto_beg": false, "sound_enabled": "true"}', encoding="utf-8")
    assert load_settings(path)["auto_beg"] is False
    assert load_settings(path)["sound_enabled"] is False


def test_context_click_feeds_once_and_cancel_restores_jump(scene):
    w = scene[0]
    w.start_play("beg")
    sid = w.play.session_id
    for _ in range(10):
        click(w)
    assert w.play.mode == "serving"
    assert w.play.session_id == sid
    assert w.controller.state == "idle"
    w.end_play("用户结束")
    click(w)
    assert w.controller.state == "jumping"


def test_drag_cancels_without_feeding_or_jumping(scene):
    w = scene[0]
    w.start_play("beg")
    QTest.mousePress(w, Qt.MouseButton.LeftButton, pos=QPoint(50, 50))
    QTest.mouseMove(w, QPoint(100, 50))
    QTest.mouseRelease(w, Qt.MouseButton.LeftButton, pos=QPoint(100, 50))
    assert w.play.mode == "none"
    assert w.controller.state == "idle"
    assert not w.controller.dragging


@pytest.mark.parametrize("sleep", ["sleep", "supine"])
def test_feed_waits_for_original_waking_route(scene, sleep):
    w = scene[0]
    w.act(sleep)
    now = 0
    while not w.controller.state.endswith("_sleep"):
        now += 1000
        step(scene, now)
    old = w.controller.state
    w.start_play("feed", "snack")
    assert w.controller.state == old
    assert w.play.mode == "none"
    states = []
    for _ in range(12):
        now += 1000
        step(scene, now)
        states.append(w.controller.state)
        if w.play.mode != "none":
            break
    assert "prone_exit" in states
    if sleep == "supine":
        assert "supine_exit" in states
    assert w.controller.state == "idle"
    assert w.play.mode == "serving"
    assert w.play.view.food == "snack"


@pytest.mark.parametrize("pause", ["menu", "dialog"])
def test_menu_and_size_dialog_pause_session_without_catchup(scene, pause):
    w = scene[0]
    w.start_play("beg")
    step(scene, 500)
    if pause == "menu":
        w.menu.popup(w.geometry().center())
    else:
        w.size_dialog()
    before = w.play.view.session_elapsed_ms
    for now in (1000, 2000, 3000, 4000):
        step(scene, now)
    assert w.play.view.session_elapsed_ms == before
    if pause == "menu":
        w.menu.close()
    else:
        w.dialog.close()
    step(scene, 4500)
    assert w.play.view.session_elapsed_ms == before + 500


def test_switching_pending_request_never_revives_previous_food(scene):
    w = scene[0]
    w.act("supine")
    w.start_play("feed", "snack")
    w.start_play("teaser")
    for now in range(1000, 10001, 1000):
        step(scene, now)
    assert w.play.mode == "teaser"
    assert w.play.view.food is None


def test_auto_beg_counts_awake_actions_but_waits_for_safe_idle(scene):
    w = scene[0]
    w.play.config = replace(w.play.config, first_beg_ms=(1000, 1000))
    # 使用真正控制器配置建立确定的自动期限。
    w.play = type(w.play)(w.play.config)
    w.act("scratch")
    step(scene, 0)
    step(scene, 1000)
    assert w.play.view.auto_due
    assert w.play.mode == "none"
    for now in range(2000, 6001, 1000):
        step(scene, now)
    assert w.play.mode == "begging"
    assert w.play.origin == "auto"
    w.set_auto_beg(False)
    assert w.play.mode == "none"
    w.start_play("beg")
    w.set_auto_beg(False)
    assert w.play.mode == "begging"


@pytest.mark.parametrize("block", ["quiet", "hidden", "sleep"])
def test_auto_clock_does_not_accumulate_when_ineligible(scene, block):
    w = scene[0]
    step(scene, 0)
    before = w.play.view.auto_remaining_ms
    if block == "quiet":
        w.set_quiet(True)
    elif block == "hidden":
        w.hide()
    else:
        w.act("sleep")
    for now in (1000, 2000, 3000):
        step(scene, now)
    assert w.play.mode == "none"
    assert w.play.view.auto_remaining_ms == before


def test_active_play_suspends_random_actions_and_end_reschedules(scene, monkeypatch):
    w = scene[0]
    w.start_play("beg")
    w.controller.next_action = 0
    monkeypatch.setattr(w.controller, "choose_action", lambda _: "scratch")
    for now in (1000, 2000, 3000):
        step(scene, now)
    assert w.controller.state == "idle"
    w.end_play("用户结束")
    assert w.controller.next_action > 3000
    step(scene, 3001)
    assert w.controller.state == "idle"


@pytest.mark.parametrize("ending", ["hide", "close", "sleep", "quiet", "switch", "quit"])
def test_all_endings_clear_decorations_pending_and_audio(scene, monkeypatch, ending):
    w = scene[0]
    stops = []
    monkeypatch.setattr(w.audio, "close", lambda: stops.append(1))
    monkeypatch.setattr(QApplication.instance(), "quit", lambda: None)
    w.start_play("beg")
    if ending == "sleep":
        w.act("sleep")
    elif ending == "quiet":
        w.set_quiet(True)
    elif ending == "switch":
        w.start_play("teaser")
        w.end_play("结束")
    else:
        getattr(w, ending)()
    assert w.play.mode == "none"
    assert w.pending_play is None
    assert not any(item.isVisible() for item in decorations(w))
    assert stops
    if ending == "quiet":
        w.start_play("beg")
        assert w.play.mode == "begging", "安静模式仍可手动互动"


def test_audio_flags_and_preference_roundtrip(scene, monkeypatch):
    w = scene[0]
    updates = []
    monkeypatch.setattr(w.audio, "update", lambda view, **flags: updates.append(flags))
    w.start_play("beg")
    assert updates[-1]["enabled"] is False
    w.set_sound_enabled(True)
    assert updates[-1]["enabled"] is True
    w.menu.popup(w.geometry().center())
    assert updates[-1]["paused"] is True
    w.menu.close()
    assert updates[-1]["paused"] is False
    w.persist()
    assert load_settings(w.settings_path)["sound_enabled"] is True
    assert w.tray.contextMenu() is w.menu


def test_repeated_teaser_uses_two_small_input_transparent_decorations(scene):
    w = scene[0]
    for i in range(100):
        w.start_play("teaser")
        scene[2][0] = w.geometry().center() + QPoint(100 + i % 5, -10)
        step(scene, i * 16)
    items = decorations(w)
    assert len(items) == 2
    assert {item.objectName() for item in items if item.isVisible()} == {"anan-play-bubble", "anan-play-toy"}
    for now in (2000, 4000, 6000):
        step(scene, now)
    assert {item.objectName() for item in items if item.isVisible()} == {"anan-play-toy"}
    for item in items:
        flags = item.windowFlags()
        assert flags & Qt.WindowType.WindowTransparentForInput
        assert flags & Qt.WindowType.WindowDoesNotAcceptFocus
        assert flags & Qt.WindowType.WindowStaysOnTopHint
        assert flags & Qt.WindowType.Tool
        assert item.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        assert item.focusPolicy() == Qt.FocusPolicy.NoFocus
        assert item.width() <= 360 and item.height() <= 150
    assert w.play.mode in ("teaser", "teaser_swipe")
    assert w.play.view.toy_position == (scene[2][0].x(), scene[2][0].y())
    assert w.controller.state == "idle"
    click(w)
    assert w.play.mode == "teaser_swipe"
    assert w.controller.state == "idle"


@pytest.mark.parametrize("size", [100, 220, 400])
def test_props_align_inside_original_canvas_and_negative_screens(scene, size, monkeypatch):
    w = scene[0]
    w.set_size(size)
    w.move(-1500, -800)
    w.start_play("feed", "snack")
    step(scene, 700)
    assert w.size().width() == size and w.frame.size().width() == 256
    assert w.frame.toImage() != w.cat_frame.toImage()
    monkeypatch.setattr(w.props, "screen_rects", lambda: [QRect(-1920, -1080, 1920, 1080)])
    w.start_play("teaser")
    scene[2][0] = QPoint(-1920, -1080)
    step(scene, 800)
    toy = next(item for item in decorations(w) if item.objectName() == "anan-play-toy")
    assert QRect(-1920, -1080, 1920, 1080).contains(toy.geometry())
    assert w.play.view.toy_position == (-1920, -1080)
    assert w.width() == size
    monkeypatch.setattr(w.props, "screen_rects", lambda: [])
    step(scene, 900)
    assert not any(item.isVisible() for item in decorations(w))


def test_cat_transition_source_never_includes_bowl_and_serving_visibly_falls(scene):
    w = scene[0]
    w.start_play("feed", "snack")
    step(scene, 0)
    first = w.frame.toImage()
    step(scene, 400)
    assert first != w.frame.toImage(), "投放需要可见的落食过程"
    cat = w.cat_frame.toImage()
    w.end_play("用户结束")
    w.refresh_frame(400)
    assert w.frame.toImage() == cat
    assert w.transition_source is None or w.transition_source.toImage() == cat


def test_disable_auto_does_not_interrupt_an_accepted_automatic_meal(scene):
    w = scene[0]
    w.play.config = replace(w.play.config, first_beg_ms=(1000, 1000))
    w.play = type(w.play)(w.play.config)
    step(scene, 0)
    step(scene, 1000)
    assert w.play.origin == "auto"
    click(w)
    assert w.play.mode == "serving"
    w.set_auto_beg(False)
    assert w.play.mode == "serving", "关闭索食只收回尚未接受的自动邀请"


def test_same_timestamp_does_not_repeat_paint_during_head_transition(scene, monkeypatch):
    w = scene[0]
    scene[2][0] = w.geometry().center() + QPoint(100, 0)
    step(scene, 100)
    assert w.transition_source is not None
    requests = []
    monkeypatch.setattr(w, "update", lambda: requests.append(1))
    for _ in range(10):
        step(scene, 100)
    assert requests == []


def test_ending_long_teaser_keeps_five_second_user_grace(scene):
    w = scene[0]
    w.play.config = replace(w.play.config, first_beg_ms=(1000, 1000))
    w.play = type(w.play)(w.play.config)
    w.start_play("teaser")
    for now in range(1000, 10001, 1000):
        step(scene, now)
    w.end_play("用户结束")
    step(scene, 11000)
    assert w.play.view.auto_due
    assert w.play.mode == "none", "刚结束的明确交互应保留五秒间隔"
    for now in range(12000, 15001, 1000):
        step(scene, now)
    assert w.play.mode == "begging"



def test_bubble_itself_animates_bounded_notes_and_freezes_during_pause(scene):
    w = scene[0]
    w.start_play("beg")
    bubble = next(item for item in decorations(w) if item.objectName() == "anan-play-bubble")
    first = bubble.grab().toImage()
    step(scene, 500)
    second = bubble.grab().toImage()
    assert first != second, "气泡窗自身应有轻量动态音符，不仅猫咪身体变化"
    w.menu.popup(w.geometry().center())
    frozen = bubble.grab().toImage()
    step(scene, 1000)
    assert frozen == bubble.grab().toImage()
    assert len(decorations(w)) == 2


def test_automatic_wander_does_not_count_as_explicit_user_input(scene, monkeypatch):
    w = scene[0]
    w.play.config = replace(w.play.config, first_beg_ms=(3000, 3000))
    w.play = type(w.play)(w.play.config)
    w.preferences["wander"] = True
    w.controller.next_action = 0
    w.controller.durations["running-left"] = w.controller.durations["running-right"] = 1000
    monkeypatch.setattr(w.controller, "choose_action", lambda _: "look")
    step(scene, 0)
    assert w.controller.state.startswith("running-")
    for now in (1000, 2000, 3000):
        step(scene, now)
    assert w.play.mode == "begging", "自动散步不应重置用户交互保护间隔"


def test_menu_freezes_cat_crossfade_as_well_as_session_clock(scene):
    w = scene[0]
    w.start_play("beg")
    step(scene, 20)
    w.menu.popup(w.geometry().center())
    before = w.frame.toImage()
    assert w.transition_source is not None
    step(scene, 1000)
    assert w.frame.toImage() == before, "暂停时不能继续推进猫咪姿势的交叉过渡"


@pytest.mark.parametrize("operation", ["menu", "dialog"])
def test_opening_controls_at_auto_deadline_does_not_start_invitation(scene, operation):
    w = scene[0]
    w.play.config = replace(w.play.config, first_beg_ms=(1000, 1000))
    w.play = type(w.play)(w.play.config)
    step(scene, 0)
    scene[1][0] = 1000
    if operation == "menu":
        w.menu.popup(w.geometry().center())
    else:
        w.size_dialog()
    assert w.play.view.auto_due
    assert w.play.mode == "none", "打开设置的明确操作不能恰好被自动索食抢占"


def test_teaser_starts_with_brief_mouse_and_click_hint(scene):
    w = scene[0]
    w.start_play("teaser")
    bubble = next(item for item in decorations(w) if item.objectName() == "anan-play-bubble")
    assert bubble.isVisible()
    assert bubble.text == "移动鼠标逗安安，点我拍一下"
    for now in (1000, 2000, 3000):
        step(scene, now)
    assert bubble.isVisible()
    step(scene, 5000)
    assert not bubble.isVisible()
    assert w.play.mode == "teaser"


@pytest.mark.parametrize("mode", ["serving", "eating"])
def test_repeated_meal_click_gives_short_feedback_without_another_meal(scene, mode):
    w = scene[0]
    w.start_play("feed")
    if mode == "eating":
        step(scene, 1000)
        step(scene, 2000)
    assert w.play.mode == mode
    sid = w.play.session_id
    before = w.play.view.phase_elapsed_ms
    for _ in range(5):
        click(w)
    bubble = next(item for item in decorations(w) if item.objectName() == "anan-play-bubble")
    assert bubble.isVisible()
    assert bubble.text == "安安正在吃呢"
    assert w.play.session_id == sid
    assert w.play.view.phase_elapsed_ms == before
    assert w.controller.state == "idle"
    for _ in range(2):
        step(scene, scene[1][0] + 1000)
    assert not bubble.isVisible()


def test_meal_feedback_pauses_and_is_cleared_on_session_replacement(scene):
    w = scene[0]
    w.start_play("feed")
    click(w)
    bubble = next(item for item in decorations(w) if item.objectName() == "anan-play-bubble")
    assert bubble.text == "安安正在吃呢"
    w.menu.popup(w.geometry().center())
    for now in (1000, 2000, 3000):
        step(scene, now)
    w.menu.close()
    assert bubble.isVisible()
    assert bubble.text == "安安正在吃呢"
    w.start_play("teaser")
    assert bubble.text == "移动鼠标逗安安，点我拍一下"
    w.end_play("用户结束")
    w.start_play("feed")
    assert not bubble.isVisible(), "新会话不能复活上一餐的点击反馈"


def test_closing_size_dialog_keeps_due_invitation_and_five_second_grace(scene):
    w = scene[0]
    w.play.config = replace(w.play.config, first_beg_ms=(1000, 1000))
    w.play = type(w.play)(w.play.config)
    w.act("scratch")
    step(scene, 0)
    step(scene, 1000)
    assert w.play.view.auto_due
    w.size_dialog()
    for now in range(2000, 7001, 1000):
        step(scene, now)
    assert w.controller.state == "idle"
    w.dialog.close()
    assert w.play.view.auto_due
    assert w.play.mode == "none", "关闭大小设置后应保留五秒明确交互保护"
    for now in range(8000, 12000, 1000):
        step(scene, now)
        assert w.play.mode == "none"
    step(scene, 12000)
    assert w.play.mode == "begging"


def test_restoring_hidden_pet_keeps_due_invitation_and_five_second_grace(scene):
    w = scene[0]
    w.play.config = replace(w.play.config, first_beg_ms=(1000, 1000))
    w.play = type(w.play)(w.play.config)
    w.act("scratch")
    step(scene, 0)
    step(scene, 1000)
    assert w.play.view.auto_due
    w.hide()
    for now in range(2000, 7001, 1000):
        step(scene, now)
    assert w.controller.state == "idle"
    w.show_pet()
    assert w.play.view.auto_due
    assert w.play.mode == "none", "恢复显示后应保留五秒交互保护，不能立即发起新邀请"
    for now in range(8000, 12000, 1000):
        step(scene, now)
        assert w.play.mode == "none"
    step(scene, 12000)
    assert w.play.mode == "begging"


def prepare_late_idle_transition(scene):
    w = scene[0]
    scene[1][0] = 100000
    w.act("scratch")
    step(scene, 100100)
    w.act("wake")
    assert w.visual_key == "idle"
    assert w.transition_source is not None
    assert w.cat_frame.toImage() != w.pixmaps["idle"][0].toImage()
    return w


def test_entering_same_idle_clip_at_late_clock_rebases_transition_to_session(scene):
    w = prepare_late_idle_transition(scene)
    w.start_play("feed")
    before = w.cat_frame.toImage()
    step(scene, 100140)
    assert w.cat_frame.toImage() != before, "切到会话时间后仍需推进已有猫咪过渡"
    step(scene, 100300)
    assert w.play.mode == "serving"
    assert w.transition_source is None
    assert w.cat_frame.toImage() == w.pixmaps["idle"][0].toImage()


def test_leaving_same_idle_clip_rebases_transition_back_to_window_clock(scene):
    w = prepare_late_idle_transition(scene)
    w.start_play("feed")
    step(scene, 100120)
    before = w.cat_frame.toImage()
    w.end_play("用户结束")
    assert w.cat_frame.toImage() == before, "退出会话也应从当前纯猫帧开始短过渡"
    step(scene, 100300)
    assert w.transition_source is None
    assert w.cat_frame.toImage() == w.pixmaps["idle"][0].toImage()


def test_closing_main_window_exits_process_without_hidden_residue(tmp_path):
    import os
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    helper = tmp_path / '关闭进程检查.py'
    helper.write_text('''from PySide6.QtCore import Qt, QTimer
from anan_pet.window import PetWindow
original_show = PetWindow.show
def show_for_check(self):
    self.setWindowOpacity(0)
    self.setWindowFlag(Qt.WindowType.WindowTransparentForInput, True)
    self.setWindowFlag(Qt.WindowType.WindowDoesNotAcceptFocus, True)
    self.tray.hide()
    original_show(self)
    QTimer.singleShot(200, self.close)
PetWindow.show = show_for_check
from anan_pet.__main__ import main
raise SystemExit(main())
''', encoding='utf-8')
    environment = os.environ.copy()
    environment['PYTHONPATH'] = str(root / 'src')
    environment['PYTHONUTF8'] = '1'
    environment['APPDATA'] = str(tmp_path / '独立偏好')
    try:
        result = subprocess.run([sys.executable, str(helper)], cwd=root, env=environment,
                                capture_output=True, text=True, encoding='utf-8', timeout=8)
    except subprocess.TimeoutExpired:
        pytest.fail('主窗口关闭后进程仍在运行，托盘已隐藏而无法退出')
    assert result.returncode == 0, result.stderr
