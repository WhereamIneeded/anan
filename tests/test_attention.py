"""验证附近鼠标关注的范围、超时和窗口交互优先级。"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF
from PySide6.QtGui import QEnterEvent
from PySide6.QtWidgets import QApplication

from anan_pet import pointer
from anan_pet.window import PetWindow


def tracker():
    assert hasattr(pointer, "AttentionTracker"), "尚未实现附近鼠标关注状态"
    return pointer.AttentionTracker()


def test_attention_keeps_outer_ring_until_exit():
    attention = tracker()
    assert attention.update((200, 0), (0, 0), 220, 0)
    assert attention.update((290, 0), (0, 0), 220, 100)
    assert not attention.update((331, 0), (0, 0), 220, 200)
    assert not attention.update((290, 0), (0, 0), 220, 300)
    assert attention.update((264, 0), (0, 0), 220, 400)


@pytest.mark.parametrize("size", [100, 220, 400])
def test_attention_scales_radii_in_negative_global_coordinates(size):
    attention = tracker()
    center = (-1200, -800)
    inner, outer = round(size * 1.2), round(size * 1.5)
    assert not attention.update((center[0] - inner - 1, center[1]), center, size, 0)
    assert attention.update((center[0] - inner, center[1]), center, size, 100)
    assert attention.update((center[0], center[1] - outer), center, size, 200)
    assert not attention.update((center[0], center[1] - outer - 1), center, size, 300)


def test_still_pointer_expires_and_needs_new_movement():
    attention = tracker()
    assert attention.update((200, 0), (0, 0), 220, 0)
    assert attention.update((200, 0), (0, 0), 220, 2999)
    assert not attention.update((200, 0), (0, 0), 220, 3001)
    assert not attention.update((200, 0), (0, 0), 220, 6000)
    assert attention.update((190, 0), (0, 0), 220, 6100)
    assert attention.update((190, 0), (0, 0), 220, 9099)
    assert not attention.update((190, 0), (0, 0), 220, 9100)


def test_only_pointer_movement_refreshes_attention_timeout():
    attention = tracker()
    assert attention.update((100, 0), (0, 0), 220, 0)
    assert attention.update((101, 0), (0, 0), 220, 2000)
    assert attention.update((101, 0), (10, 0), 220, 4000)
    assert not attention.update((101, 0), (20, 0), 220, 5000)


def test_outer_ring_movement_refreshes_timeout_at_expiry_boundary():
    attention = tracker()
    assert attention.update((200, 0), (0, 0), 220, 0)
    assert attention.update((290, 0), (0, 0), 220, 100)
    assert attention.update((290, 0), (0, 0), 220, 3099)
    assert attention.update((291, 0), (0, 0), 220, 3100)
    assert attention.update((291, 0), (0, 0), 220, 6099)
    assert not attention.update((291, 0), (0, 0), 220, 6100)
    assert not attention.update((292, 0), (0, 0), 220, 6200)
    assert attention.update((264, 0), (0, 0), 220, 6300)


def test_ineligible_samples_cancel_attention_without_replaying_movement():
    attention = tracker()
    assert attention.update((100, 0), (0, 0), 220, 0)
    assert not attention.update((120, 0), (0, 0), 220, 100, eligible=False)
    assert not attention.update((120, 0), (0, 0), 220, 200)
    assert attention.update((130, 0), (0, 0), 220, 300)


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


def sample(scene, offset, now):
    window, clock, cursor = scene
    clock[0] = now
    cursor[0] = window.geometry().center() + QPoint(*offset)
    window.advance()
    return window


def test_nearby_pointer_outside_window_controls_look(scene):
    window = sample(scene, (200, 0), 0)
    assert not window.geometry().contains(scene[2][0])
    assert window.visual_key == "look"
    assert window.look_index == 4
    assert window.controller.state == "idle", "附近移动不能触发跳跃"
    sample(scene, (290, 0), 100)
    assert window.visual_key == "look"
    sample(scene, (331, 0), 200)
    assert window.visual_key == "idle"
    sample(scene, (290, 0), 300)
    assert window.visual_key == "idle"
    sample(scene, (260, 0), 400)
    assert window.visual_key == "look"


def test_real_enter_and_leave_do_not_cancel_nearby_attention(scene):
    window = sample(scene, (200, 0), 0)
    local = QPointF(window.width() / 2, window.height() / 2)
    QApplication.sendEvent(window, QEnterEvent(local, local, QPointF(window.geometry().center())))
    QApplication.sendEvent(window, QEvent(QEvent.Type.Leave))
    sample(scene, (201, 0), 100)
    assert window.visual_key == "look"
    assert window.controller.state == "idle"


def test_still_pointer_on_cat_returns_to_idle_and_resumes_random_schedule(scene, monkeypatch):
    window = scene[0]
    window.controller.next_action = 0
    monkeypatch.setattr(window.controller, "choose_action", lambda now_ms: "scratch")
    sample(scene, (40, 0), 0)
    sample(scene, (40, 0), 2999)
    grace_deadline = window.controller.next_action
    assert grace_deadline == 2999 + window.controller.config.attention_grace_ms
    sample(scene, (40, 0), 3001)
    assert window.visual_key == "idle"
    sample(scene, (40, 0), 6000)
    assert window.controller.next_action == grace_deadline
    sample(scene, (40, 0), grace_deadline)
    assert window.controller.state == "scratch", "静止停留在猫身上也应恢复随机调度"


def test_movement_after_timeout_starts_attention_again(scene):
    window = sample(scene, (200, 0), 0)
    sample(scene, (200, 0), 3001)
    assert window.visual_key == "idle"
    sample(scene, (190, 0), 6100)
    assert window.visual_key == "look"


@pytest.mark.parametrize("state", ["jumping", "scratch", "prone_enter", "prone_sleep", "prone_exit", "supine_enter", "supine_sleep", "supine_exit"])
def test_active_actions_take_priority_over_nearby_movement(scene, state):
    window = sample(scene, (200, 0), 0)
    window.controller.state = state
    window.controller.started = 0
    window.controller.sleep_until = 100000
    sample(scene, (190, 0), 100)
    assert window.controller.state == state
    assert window.visual_key == state
    window.controller.state = "idle"
    sample(scene, (190, 0), 200)
    assert window.visual_key == "idle", "动作期间的移动不能在动作结束后补触发关注"


def test_dragging_takes_priority_and_release_requires_new_movement(scene):
    window = sample(scene, (200, 0), 0)
    window.act("drag_start")
    sample(scene, (190, 0), 100)
    assert window.controller.dragging
    assert window.visual_key == "running-right"
    window.act("drag_end")
    sample(scene, (190, 0), 200)
    assert window.visual_key == "idle"
    assert window.controller.state == "idle"
    sample(scene, (180, 0), 300)
    assert window.visual_key == "look"


@pytest.mark.parametrize("pause", ["menu", "dialog", "hidden"])
def test_window_operations_pause_attention(scene, pause):
    window = sample(scene, (200, 0), 0)
    if pause == "menu":
        window.menu.popup(window.geometry().center())
    elif pause == "dialog":
        window.size_dialog()
    else:
        window.hide()
    sample(scene, (190, 0), 100)
    assert window.visual_key == "idle"
    if pause == "menu":
        window.menu.close()
    elif pause == "dialog":
        window.dialog.close()
    else:
        window.show()
    sample(scene, (190, 0), 200)
    assert window.visual_key == "idle"
    sample(scene, (180, 0), 300)
    assert window.visual_key == "look"


@pytest.mark.parametrize("size", [100, 220, 400])
def test_window_uses_display_width_for_attention_at_negative_positions(scene, size):
    window = scene[0]
    window.set_size(size)
    window.move(-1500, -800)
    sample(scene, (round(size * 1.2), 0), 0)
    assert window.visual_key == "look"
    sample(scene, (round(size * 1.5) + 1, 0), 100)
    assert window.visual_key == "idle"
