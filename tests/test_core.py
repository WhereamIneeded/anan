"""验证鼠标手势、资源、设置和行为切换的用户可见规则。"""

import importlib.util
import json
import random
from pathlib import Path

import pytest


def 模块(名称):
    try:
        可用 = importlib.util.find_spec("anan_pet." + 名称)
    except ModuleNotFoundError:
        可用 = None
    assert 可用 is not None, f"尚未实现模块：{名称}"
    return __import__("anan_pet." + 名称, fromlist=[名称])


def test_hover_and_click_drag():
    Gesture = 模块("pointer").Gesture
    g = Gesture(10)
    assert not g.release()
    g.press(100, 100)
    assert not g.move(103, 102)
    assert g.release()
    assert not g.release()
    g.press(100, 100)
    assert g.move(115, 100)
    assert g.move(100, 100)
    assert not g.release()


def test_settings_roundtrip_and_invalid(tmp_path):
    s = 模块("settings")
    p = tmp_path / "中文 偏好.json"
    assert s.load_settings(p)["size"] == 220
    s.save_settings(p, {"size": 310, "position": [-200, 30], "quiet": True})
    assert s.load_settings(p)["position"] == [-200, 30]
    assert s.load_settings(p)["size"] == 310
    p.write_text('{"size": "坏数据", "position": [null, 1]}', encoding="utf-8")
    assert s.load_settings(p)["size"] == 220
    p.write_text('{"size": 800}', encoding="utf-8")
    assert s.load_settings(p)["size"] == 400


def test_visible_position_and_resize_anchor():
    s = 模块("settings")
    assert s.visible_position(-5000, 3000, 220, 220, [(0, 0, 1920, 1080)]) == (0, 860)
    assert s.visible_position(-200, 30, 220, 220, [(-1920, 0, 1920, 1080)]) == (-220, 30)
    assert s.resize_position(100, 100, 220, 220, 400, 400) == (10, -80)


def 控制器():
    b = 模块("behavior")
    durations = {key: 100 for key in ["idle", "jumping", "waving", "scratch", "wash", "yawn", "stretch", "prone_enter", "prone_sleep", "prone_exit", "supine_enter", "supine_sleep", "supine_exit", "running-left", "running-right", "waiting", "running", "review", "failed", "look"]}
    return b.BehaviorController(durations, random.Random(2))


def test_hover_never_changes_to_jump():
    b = 控制器()
    for t in range(0, 500, 10):
        b.handle("hover", t)
        assert b.tick(t) != "jumping"
    b.handle("click", 500)
    assert b.tick(500) == "jumping"
    assert b.tick(650) == "idle"


def test_drag_release_ignores_click():
    b = 控制器()
    b.handle("drag_start", 1)
    b.handle("click", 2)
    assert b.tick(2) != "jumping"
    b.handle("drag_end", 3)
    assert b.tick(3) == "idle"


@pytest.mark.parametrize("event,expected", [("sleep", ["prone_enter", "prone_sleep", "prone_exit", "jumping", "idle"]), ("supine", ["prone_enter", "supine_enter", "supine_sleep", "supine_exit", "prone_exit", "jumping", "idle"])])
def test_sleep_wakes_before_jumping(event, expected):
    b = 控制器()
    b.handle(event, 0)
    states = [b.tick(0)]
    now = 0
    while not b.state.endswith("_sleep"):
        now += 110
        states.append(b.tick(now))
    b.handle("hover", now + 1)
    assert b.state.endswith("_sleep")
    b.handle("click", now + 2)
    for _ in range(5):
        now += 110
        state = b.tick(now)
        if state != states[-1]:
            states.append(state)
        if state == "idle":
            break
    assert states == expected


def test_click_during_enter_finishes_transition():
    b = 控制器()
    b.handle("supine", 0)
    b.tick(110)
    assert b.state == "supine_enter"
    b.handle("click", 120)
    assert b.state == "supine_enter"
    assert b.tick(220) == "supine_exit"


def test_random_no_jump_and_no_repeat():
    b = 控制器()
    actions = [b.choose_action() for _ in range(200)]
    assert "jumping" not in actions
    assert all(a != c for a, c in zip(actions, actions[1:]))
    other = 控制器()
    assert actions == [other.choose_action() for _ in range(200)]


def test_resource_counts_and_complete():
    a = 模块("animation")
    clips = a.load_animations(a.resource_root())
    expected = {"idle": 6, "running-right": 8, "running-left": 8, "waving": 4, "jumping": 5, "failed": 8, "waiting": 6, "running": 6, "review": 6, "look": 16}
    for key, count in expected.items():
        assert len(clips[key].frames) == count
    for clip in clips.values():
        assert len(clip.frames) == len(clip.durations)
        assert all(p.is_file() for p in clip.frames)
        assert all(ms > 0 for ms in clip.durations)
    idle = clips["idle"]
    assert idle.frame_index(0) == 0
    assert idle.frame_index(idle.total_ms + 1) == 0


def test_resources_from_chinese_path(tmp_path):
    import shutil
    a = 模块("animation")
    target = tmp_path / "中文 空格目录" / "assets"
    shutil.copytree(a.resource_root(), target)
    clips = a.load_animations(target)
    assert clips["jumping"].frames[0].is_file()


def test_build_environment_excludes_foreign_dll_paths():
    import runpy
    script = Path(__file__).resolve().parents[1] / "scripts/构建环境.py"
    assert script.exists(), "尚未隔离构建依赖搜索路径"
    build_environment = runpy.run_path(str(script))["build_environment"]
    env = build_environment({"PATH": "C:/外部工具/Poppler", "SystemRoot": "C:/Windows", "PYTHONPATH": "C:/外部Python"}, "C:/项目/.venv/Scripts/python.exe", "C:/Python310")
    assert "Poppler" not in env["PATH"]
    assert "PYTHONPATH" not in env
    assert "System32" in env["PATH"]
