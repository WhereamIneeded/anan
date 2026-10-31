"""真实离屏窗口的外观切换、恢复及失败回退。"""

import os
import json
import socket

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication, QWidget

from anan_pet.settings import load_settings
from anan_pet.window import PetWindow
from test_appearance import PET_ID, make_package, pixels


@pytest.fixture
def scene(tmp_path):
    app = QApplication.instance() or QApplication([])
    root = tmp_path / "宠物" / PET_ID
    make_package(root)
    window = PetWindow(tmp_path / "偏好.json")
    window.timer.stop()
    yield window, root
    window.close()


def test_restore_roundtrip_preserves_pixels_and_preferences(scene):
    window, root = scene
    original = {k: list(map(pixels, frames)) for k, frames in window.pixmaps.items()}
    before = dict(window.preferences)
    geometry = window.geometry()
    assert window.activate_custom_pet(PET_ID)
    assert window.pet_name == "测试副本"
    assert window.windowTitle() == "测试副本 · 桌面宠物"
    assert window.restore_default_pet()
    assert window.pet_name == "安安"
    assert {k: list(map(pixels, frames)) for k, frames in window.pixmaps.items()} == original
    assert window.geometry() == geometry
    assert {k: v for k, v in window.preferences.items() if k not in ("active_pet", "custom_pet")} == {k: v for k, v in before.items() if k not in ("active_pet", "custom_pet")}
    assert root.is_dir() and len(list((root / "帧").glob("*.png"))) == 155
    assert window.restore_default_pet()
    assert window.activate_custom_pet(PET_ID)
    assert load_settings(window.settings_path)["active_pet"] == PET_ID
    assert window.restore_default_pet()
    assert load_settings(window.settings_path)["active_pet"] is None
    assert load_settings(window.settings_path)["custom_pet"] == PET_ID


@pytest.mark.parametrize("state", ["sleeping", "drag", "feed", "teaser"])
def test_restore_clears_sessions_and_old_visuals(scene, state):
    window, root = scene
    assert window.activate_custom_pet(PET_ID)
    if state in ("feed", "teaser"):
        window.start_play(state)
    elif state == "drag":
        window.controller.handle("drag_start", window.now())
        window.gesture.press(0, 0)
        window.gesture.move(50, 50)
        window.drag_offset = (3, 4)
    else:
        window.act("sleep")
        window.controller.tick(window.controller.started + window.clips["prone_enter"].total_ms)
        assert window.controller.state == "prone_sleep"
    window.transition_source = window.frame
    window.attention.active = True
    window.look_index = 8
    old_generation = window.teaser_exit.generation if window.teaser_exit else None
    if state == "teaser":
        assert old_generation is not None and window.teaser_exit.enabled
    assert window.restore_default_pet()
    assert window.controller.state == "idle" and not window.controller.dragging
    assert window.play.mode == "none" and window.pending_play is None
    assert window.drag_offset is None and window.gesture.origin is None
    assert not window.attention.active and window.look_index == 0
    assert window.transition_source is None
    assert window.transition_duration == 0
    assert window.teaser_exit is None or not window.teaser_exit.enabled
    assert not any(widget.isVisible() for widget in window.findChildren(QWidget) if widget.objectName().startswith("anan-play-"))
    if old_generation is not None:
        window.start_play("teaser")
        session = window.play.session_id
        window.handle_teaser_double_click(old_generation)
        assert window.play.session_id == session and window.play.mode != "none"


def test_invalid_and_save_failure_leave_current_appearance(scene, monkeypatch):
    window, root = scene
    original = window.pixmaps
    preferences = dict(window.preferences)
    assert not window.activate_custom_pet("../越界")
    assert window.pixmaps is original and window.preferences == preferences
    def fail(*args):
        raise OSError("测试保存失败")
    monkeypatch.setattr("anan_pet.window.save_settings", fail)
    assert not window.activate_custom_pet(PET_ID)
    assert window.pixmaps is original and window.preferences == preferences
    assert window.appearance_error


def test_restart_selection_and_broken_startup_fallback(scene):
    window, root = scene
    assert window.activate_custom_pet(PET_ID)
    second = PetWindow(window.settings_path)
    second.timer.stop()
    assert second.pet_name == "测试副本"
    second.close()
    (root / "宠物.json").unlink()
    fallback = PetWindow(window.settings_path)
    fallback.timer.stop()
    assert fallback.pet_name == "安安" and fallback.appearance_error
    assert fallback.preferences["active_pet"] is None
    assert fallback.preferences["custom_pet"] == PET_ID
    assert not fallback.custom_pet_action.isEnabled()
    fallback.close()


def test_menu_has_no_empty_entry_and_default_is_idempotent(tmp_path):
    app = QApplication.instance() or QApplication([])
    window = PetWindow(tmp_path / "偏好.json")
    window.timer.stop()
    assert not window.custom_pet_action.isEnabled()
    assert not window.restore_default_action.isEnabled()
    assert window.appearance_error is None
    assert window.restore_default_pet()
    window.close()


def test_restore_is_offline_and_keeps_nondefault_preferences(scene, monkeypatch):
    window, root = scene
    window.set_size(280)
    window.move(110, 120)
    window.set_quiet(True)
    window.set_wander(True)
    window.set_auto_beg(False)
    window.set_sound_enabled(True)
    window.persist()
    assert window.activate_custom_pet(PET_ID)
    expected = dict(window.preferences)
    def network_forbidden(*args, **kwargs):
        pytest.fail("恢复默认不应访问网络")
    monkeypatch.setattr(socket, "create_connection", network_forbidden)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert window.restore_default_pet()
    for key in ("size", "position", "quiet", "wander", "auto_beg", "sound_enabled"):
        assert window.preferences[key] == expected[key]
    restart = PetWindow(window.settings_path)
    restart.timer.stop()
    assert restart.pet_name == "安安"
    assert restart.preferences["custom_pet"] == PET_ID
    restart.close()


def test_failed_restore_preserves_custom_and_failed_fallback_save_still_starts(scene, monkeypatch):
    window, root = scene
    assert window.activate_custom_pet(PET_ID)
    original, preferences = window.pixmaps, dict(window.preferences)
    def fail(*args):
        raise OSError("测试禁止写入")
    monkeypatch.setattr("anan_pet.window.save_settings", fail)
    assert not window.restore_default_pet()
    assert window.pixmaps is original and window.preferences == preferences
    (root / "宠物.json").unlink()
    fallback = PetWindow(window.settings_path)
    fallback.timer.stop()
    assert fallback.pet_name == "安安" and "未保存" in fallback.appearance_error
    assert fallback.preferences["custom_pet"] == PET_ID
    fallback.close()


def self_link(root):
    """创建真实目录自链接，暴露路径解析循环。"""
    root.parent.mkdir(parents=True, exist_ok=True)
    try:
        root.symlink_to(root, target_is_directory=True)
    except OSError:
        pytest.skip("当前Windows账号不能创建目录符号链接")


def test_self_link_activation_keeps_current_appearance(tmp_path):
    app = QApplication.instance() or QApplication([])
    window = PetWindow(tmp_path / "偏好.json")
    window.timer.stop()
    original, preferences = window.pixmaps, dict(window.preferences)
    root = tmp_path / "宠物" / PET_ID
    self_link(root)
    try:
        assert not window.activate_custom_pet(PET_ID)
        assert window.pixmaps is original and window.preferences == preferences
        assert window.appearance_error
    finally:
        window.close()


@pytest.mark.parametrize("active", [PET_ID, None])
def test_self_link_current_or_remembered_does_not_break_default_startup(tmp_path, active):
    app = QApplication.instance() or QApplication([])
    self_link(tmp_path / "宠物" / PET_ID)
    path = tmp_path / "偏好.json"
    path.write_text(json.dumps({"active_pet": active, "custom_pet": PET_ID, "size": 280, "quiet": True}), encoding="utf-8")
    window = PetWindow(path)
    window.timer.stop()
    try:
        assert window.pet_name == "安安"
        assert window.preferences["active_pet"] is None
        assert window.preferences["custom_pet"] == PET_ID
        assert window.preferences["size"] == 280 and window.preferences["quiet"]
        assert not window.custom_pet_action.isEnabled()
        assert bool(window.appearance_error) == (active is not None)
    finally:
        window.close()


def test_custom_pointer_turn_preserves_transition_without_default_body(scene, monkeypatch):
    window, root = scene
    assert window.activate_custom_pet(PET_ID)
    clock = [window.now()]
    cursor = [window.geometry().center() + QPoint(200, 0)]
    monkeypatch.setattr(window, "now", lambda: clock[0])
    monkeypatch.setattr("anan_pet.window.QCursor.pos", lambda: cursor[0])
    duration = window.clips["look"].transition_ms
    window.update_attention(clock[0])
    window.refresh_frame(clock[0])
    assert window.visual_key == "look" and window.visual_index == 4
    clock[0] += duration + 1
    window.refresh_frame(clock[0])
    assert window.transition_source is None
    right_frame = pixels(window.frame)
    cursor[0] = window.geometry().center() + QPoint(-200, 0)
    clock[0] += 1
    window.update_attention(clock[0])
    window.refresh_frame(clock[0])
    assert window.visual_key == "look" and window.visual_index == 12
    assert window.transition_source is not None
    assert window.transition_duration == duration
    assert window.transition_body_top is None
    assert pixels(window.frame) == right_frame
    clock[0] += duration + 1
    window.refresh_frame(clock[0])
    assert window.transition_source is None
    assert pixels(window.frame) == pixels(window.pixmaps["look"][12])
