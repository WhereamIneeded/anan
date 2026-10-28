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


def test_look_changes_head_and_neck_without_changing_lower_body(pet):
    base = pet.pixmaps["idle"][0].toImage()
    for pixmap in pet.pixmaps["look"]:
        assert pixmap.toImage().copy(45, 168, 180, 80) == base.copy(45, 168, 180, 80)


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
    assert max(scratch.durations[1:-1]) <= 180
    assert 100 <= scratch.blend_ms <= 160
    samples = {(i, j, round(t * 16)) for i, j, t in (scratch.sample(ms) for ms in range(0, scratch.total_ms, 16))}
    assert len(samples) >= 40


def test_scratch_timing_is_twice_the_original_without_changing_frames_or_anchor():
    scratch = load_animations(resource_root())["scratch"]
    assert scratch.durations == [240, 160, 160, 160, 140, 130, 120, 120, 120, 120, 130, 130, 160, 160, 160, 300]
    assert scratch.total_ms == 2510
    assert scratch.blend_ms == 120
    assert scratch.anchor == (123, 241)
    assert [path.name for path in scratch.frames] == [f"{index:02}.png" for index in range(16)]


def test_registering_scratch_preserves_slower_timing_and_other_animations(tmp_path):
    import json
    import runpy

    config = tmp_path / "assets/animations.json"
    config.parent.mkdir()
    config.write_bytes((resource_root() / "animations.json").read_bytes())
    before = json.loads(config.read_text(encoding="utf-8"))
    register = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts/准备挠耳连续素材.py"))["register_animation"]
    register(tmp_path)
    after = json.loads(config.read_text(encoding="utf-8"))
    assert after["scratch"]["durations"] == [240, 160, 160, 160, 140, 130, 120, 120, 120, 120, 130, 130, 160, 160, 160, 300]
    assert after["scratch"]["blend_ms"] == 120
    assert after["scratch"]["frames"] == before["scratch"]["frames"]
    assert after["scratch"]["anchor"] == before["scratch"]["anchor"]
    assert {key: clip for key, clip in after.items() if key != "scratch"} == {key: clip for key, clip in before.items() if key != "scratch"}


def test_displayed_idle_has_no_green_fringe(pet):
    image = pet.pixmaps["idle"][0].toImage()
    for y in range(image.height()):
        for x in range(image.width()):
            color = image.pixelColor(x, y)
            if color.alpha():
                assert color.green() <= max(color.red(), color.blue()), f"轮廓仍有绿溢色：{x}, {y}"


def test_despill_preserves_fur_eye_colors_and_soft_transparency():
    from PySide6.QtGui import QImage
    from anan_pet.rendering import remove_green_spill

    app = QApplication.instance() or QApplication([])
    source = QImage(5, 1, QImage.Format.Format_RGBA8888)
    colors = [(180, 245, 120, 128), (185, 160, 132, 255), (110, 126, 150, 255), (235, 160, 165, 255), (0, 0, 0, 0)]
    for index, rgba in enumerate(colors):
        source.setPixelColor(index, 0, QColor(*rgba))
    original = QPixmap.fromImage(source)
    cleaned = remove_green_spill(original).toImage()
    assert cleaned.pixelColor(0, 0).green() <= cleaned.pixelColor(0, 0).red()
    assert cleaned.pixelColor(0, 0).alpha() == original.toImage().pixelColor(0, 0).alpha()
    for index in range(1, 5):
        assert cleaned.pixelColor(index, 0) == original.toImage().pixelColor(index, 0)


@pytest.mark.parametrize("direction", [6, 7, 8, 9, 10])
def test_lowered_head_preserves_original_muzzle_and_chin(pet, direction):
    from anan_pet.rendering import remove_green_spill

    source = remove_green_spill(QPixmap(str(pet.clips["look"].frames[direction]))).toImage()
    actual = pet.pixmaps["look"][direction].toImage()
    assert actual.copy(80, 118, 90, 32) == source.copy(80, 118, 90, 32), "低头时嘴和下巴不能被静止胸毛覆盖"


def test_hover_renderer_preserves_lowered_head_after_transition(pet, monkeypatch):
    from PySide6.QtCore import QPoint
    from anan_pet.rendering import remove_green_spill

    monkeypatch.setattr("anan_pet.window.QCursor.pos", lambda: pet.geometry().center() + QPoint(-38, 92))
    pet.update_attention(100)
    pet.refresh_frame(100)
    pet.refresh_frame(200)
    assert pet.look_index == 9
    source = remove_green_spill(QPixmap(str(pet.clips["look"].frames[9]))).toImage()
    assert pet.frame.toImage().copy(80, 118, 90, 32) == source.copy(80, 118, 90, 32), "播放器最后的身体覆盖也不能切掉下巴"


@pytest.mark.parametrize("size", [100, 220, 400])
def test_all_hover_directions_preserve_face_and_stable_lower_body(pet, monkeypatch, size):
    import math
    from PySide6.QtCore import QPoint
    from anan_pet.rendering import remove_green_spill

    pet.set_size(size)
    body = pet.pixmaps["idle"][0].toImage().copy(0, 168, 256, 88)
    for direction in range(16):
        angle = math.radians(direction * 22.5)
        delta = QPoint(round(size * 0.9 * math.sin(angle)), round(-size * 0.9 * math.cos(angle)))
        monkeypatch.setattr("anan_pet.window.QCursor.pos", lambda delta=delta: pet.geometry().center() + delta)
        now = direction * 200
        pet.update_attention(now)
        pet.refresh_frame(now)
        pet.refresh_frame(now + 100)
        assert pet.look_index == direction
        source = remove_green_spill(QPixmap(str(pet.clips["look"].frames[direction]))).toImage()
        assert pet.frame.toImage().copy(80, 118, 90, 32) == source.copy(80, 118, 90, 32)
        assert pet.frame.toImage().copy(0, 168, 256, 88) == body
        assert pet.controller.state == "idle", "悬停不能触发跳跃"


def test_return_from_lowered_head_does_not_cut_chin_during_transition(pet):
    from anan_pet.rendering import blend_pixmaps

    start = pet.pixmaps["look"][9]
    pet.frame = start
    pet.visual_key = "look"
    pet.refresh_frame(0)
    pet.refresh_frame(40)
    expected = blend_pixmaps(start, pet.pixmaps["idle"][0], 0.5).toImage()
    assert pet.frame.toImage().copy(80, 118, 90, 32) == expected.copy(80, 118, 90, 32)
    pet.refresh_frame(80)
    assert pet.frame.toImage() == pet.pixmaps["idle"][0].toImage()


def test_turning_starts_at_last_displayed_pose_and_finishes_at_target(pet, monkeypatch):
    from PySide6.QtCore import QPoint

    monkeypatch.setattr("anan_pet.window.QCursor.pos", lambda: pet.geometry().center() + QPoint(-38, 92))
    pet.update_attention(0)
    pet.refresh_frame(0)
    pet.refresh_frame(100)
    previous = pet.frame.toImage()
    monkeypatch.setattr("anan_pet.window.QCursor.pos", lambda: pet.geometry().center() + QPoint(0, 100))
    pet.update_attention(200)
    pet.refresh_frame(200)
    assert pet.look_index == 8
    assert pet.frame.toImage() == previous, "转头应从刚显示的画面开始，不应瞬间跳到下一方向"
    pet.refresh_frame(300)
    assert pet.frame.toImage() == pet.pixmaps["look"][8].toImage()


def test_pose_anchor_aligns_whole_frame_without_changing_shape(pet):
    from PySide6.QtGui import QPainter
    from anan_pet.rendering import align_pixmap

    source = QPixmap(256, 256)
    source.fill(Qt.GlobalColor.transparent)
    painter = QPainter(source)
    painter.fillRect(80, 150, 20, 50, QColor("white"))
    painter.fillRect(100, 200, 1, 1, QColor("red"))
    painter.end()
    aligned = align_pixmap(source, (100, 200)).toImage()
    assert aligned.pixelColor(123, 241) == QColor("red")
    assert aligned.pixelColor(103, 191) == QColor("white")
    assert aligned.pixelColor(102, 191).alpha() == 0
