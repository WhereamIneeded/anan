"""防止全身闪烁、透明渐变变暗及静止时无效重绘。"""

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import QApplication

from anan_pet.animation import AnimationClip, load_animations, resource_root
from anan_pet.window import PetWindow


@pytest.fixture
def pet(tmp_path):
    app = QApplication.instance() or QApplication([])
    window = PetWindow(tmp_path / "偏好.json")
    window.timer.stop()
    yield window
    window.tray.hide()
    window.close()


def test_idle_body_stays_identical_during_blink(pet):
    frames = [pixmap.toImage() for pixmap in pet.pixmaps["idle"]]
    body = frames[0].copy(50, 128, 175, 120)
    assert all(frame.copy(50, 128, 175, 120) == body for frame in frames)
    assert any(frame.copy(95, 95, 60, 25) != frames[0].copy(95, 95, 60, 25) for frame in frames[1:]), "需要保留眨眼"


def test_interpolated_blink_keeps_transparent_body_edges_unchanged(pet):
    pet.hovering = False
    body = pet.pixmaps["idle"][0].toImage().copy(0, 128, 256, 128)
    for now in range(3120, 3630, 16):
        pet.refresh_frame(now)
        assert pet.frame.toImage().copy(0, 128, 256, 128) == body


def test_idle_waits_between_short_blinks():
    idle = load_animations(resource_root())["idle"]
    assert idle.durations[0] >= 2500
    assert sum(idle.durations[1:4]) <= 250


def test_clip_blends_neighbors_without_wrapping_last_pose():
    clip = AnimationClip([Path("a"), Path("b")], [100, 100], blend_ms=60)
    assert clip.sample(20) == (0, 1, 0)
    assert clip.sample(70) == (0, 1, 0.5)
    assert clip.sample(100) == (1, 1, 0)
    assert clip.sample(199) == (1, 1, 0)
    assert clip.sample(200) == (1, 1, 0)
    assert clip.sample(201) == (1, 1, 0)
    clip.loop = True
    assert clip.frame_index(201) == 0


def test_blending_does_not_dim_identical_opaque_pixels(pet):
    from anan_pet.rendering import blend_pixmaps
    left = QPixmap(8, 8)
    left.fill(QColor(230, 210, 180, 255))
    right = left.copy()
    for amount in (0.25, 0.5, 0.75):
        color = blend_pixmaps(left, right, amount).toImage().pixelColor(4, 4)
        assert color.alpha() >= 254
        assert max(abs(a - b) for a, b in zip(color.getRgb()[:3], (230, 210, 180))) <= 1
    left.fill(Qt.GlobalColor.transparent)
    right.fill(Qt.GlobalColor.transparent)
    assert blend_pixmaps(left, right, 0.5).toImage().pixelColor(0, 0).alpha() == 0


def test_still_pose_does_not_request_duplicate_repaints(pet, monkeypatch):
    monkeypatch.setattr(pet, "now", lambda: 100)
    pet.advance()
    requests = []
    monkeypatch.setattr(pet, "update", lambda: requests.append(1))
    for _ in range(10):
        pet.advance()
    assert requests == []


def test_animation_timer_uses_precise_refresh(pet):
    assert pet.timer.timerType() == Qt.TimerType.PreciseTimer
    assert pet.timer.interval() <= 17


def test_look_changes_head_without_changing_body(pet):
    base = pet.pixmaps["idle"][0].toImage()
    for pixmap in pet.pixmaps["look"]:
        assert pixmap.toImage().copy(45, 128, 180, 120) == base.copy(45, 128, 180, 120)


def test_look_direction_has_center_dead_zone_and_boundary_hysteresis():
    import math
    from anan_pet.pointer import look_direction
    assert look_direction(1, -1, 4) == 4
    def direction(angle, previous):
        radians = math.radians(angle)
        return look_direction(100 * math.sin(radians), -100 * math.cos(radians), previous)
    assert direction(12, 0) == 0
    assert direction(16, 0) == 1
    assert direction(10, 1) == 1
    assert direction(6, 1) == 0


@pytest.mark.parametrize("interval", [16, 33])
def test_walking_speed_is_independent_of_refresh_rate(pet, monkeypatch, interval):
    pet.preferences["wander"] = True
    pet.controller.state = "running-right"
    pet.controller.started = 0
    pet.move(100, 100)
    for now in [*range(0, 1000, interval), 1000]:
        monkeypatch.setattr(pet, "now", lambda t=now: t)
        pet.advance()
    assert abs(pet.x() - 130) <= 1


def test_scratch_contains_continuous_poses_and_short_transitions():
    scratch = load_animations(resource_root())["scratch"]
    assert len(set(scratch.frames)) == 16
    assert max(scratch.durations[1:-1]) <= 90
    assert 40 <= scratch.blend_ms <= 80
    samples = {(i, j, round(t * 16)) for i, j, t in (scratch.sample(ms) for ms in range(0, scratch.total_ms, 16))}
    assert len(samples) >= 40
