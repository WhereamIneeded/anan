"""验证动作阶段、重复指令、冷却和配置变更带来的实际行为。"""

import json
import random

import pytest

from anan_pet.animation import load_animations, resource_root
from anan_pet.behavior import BehaviorController, parse_behaviors


def controller():
    clips = load_animations(resource_root())
    return BehaviorController({name: 100 for name in clips}, random.Random(7))


def test_repeated_sleep_request_does_not_wake_and_restart():
    pet = controller()
    pet.handle("sleep", 0)
    pet.tick(100)
    assert pet.state == "prone_sleep"
    deadline = pet.sleep_until
    pet.handle("sleep", 120)
    assert pet.tick(130) == "prone_sleep", "再次要求睡觉不能先叫醒再重新趴下"
    assert pet.sleep_until == deadline


def test_repeated_clicks_during_wakeup_produce_one_jump():
    pet = controller()
    pet.handle("supine", 0)
    pet.tick(100)
    pet.tick(200)
    pet.handle("click", 201)
    states = []
    for now in range(210, 800, 10):
        if now < 300:
            pet.handle("click", now)
        state = pet.tick(now)
        if not states or state != states[-1]:
            states.append(state)
    assert states == ["supine_exit", "prone_exit", "jumping", "idle"]


def test_walking_repeats_while_long_drag_is_active():
    clip = load_animations(resource_root())["running-right"]
    assert clip.frame_index(clip.total_ms + 1) == 0, "长拖动不能冻结在最后一个走路姿势"


def test_hover_postpones_random_action_without_waking_sleep():
    pet = controller()
    pet.next_action = 100
    pet.handle("hover", 100)
    assert pet.tick(100) == "idle"
    pet.handle("sleep", 200)
    pet.tick(300)
    pet.handle("hover", 400)
    assert pet.tick(400) == "prone_sleep"


def test_custom_stage_names_use_configured_wakeup_route():
    durations = {name: 100 for name in ("idle", "jumping", "lower", "doze", "rise")}
    config = parse_behaviors({"idle_interval_ms": [1000, 1000], "actions": {"nap": {"start": ["lower"], "loop": "doze", "end": ["rise"], "hold_ms": [500, 500]}}}, durations)
    pet = BehaviorController(durations, random.Random(1), config)
    pet.handle("nap", 0)
    assert (pet.state, pet.phase) == ("lower", "start")
    assert pet.tick(100) == "doze"
    assert pet.phase == "loop"
    pet.handle("click", 101)
    assert pet.tick(102) == "rise"
    assert pet.phase == "end"
    assert pet.tick(202) == "jumping"
    assert pet.tick(302) == "idle"


def test_random_cooldown_uses_elapsed_time_and_keeps_manual_action_available():
    clips = load_animations(resource_root())
    data = json.loads((resource_root() / "behaviors.json").read_text(encoding="utf-8"))
    for name, info in data["actions"].items():
        info["weight"] = 1 if name == "scratch" else 0
    data["actions"]["scratch"]["cooldown_ms"] = 60000
    pet = BehaviorController({name: 100 for name in clips}, random.Random(1), parse_behaviors(data, clips))
    assert pet.choose_action(0) == "scratch"
    pet.handle("scratch", 0)
    assert pet.choose_action(1000) == "idle"
    pet.handle("scratch", 1000)
    assert pet.state == "scratch"
    assert pet.choose_action(60999) == "idle"
    assert pet.choose_action(61000) == "scratch"


def test_drag_cancels_queued_wakeup_jump():
    pet = controller()
    pet.handle("supine", 0)
    pet.tick(100)
    pet.tick(200)
    pet.handle("click", 210)
    pet.handle("drag_start", 220)
    pet.set_drag_direction("left", 230)
    assert (pet.state, pet.phase) == ("running-left", "drag")
    pet.handle("drag_end", 300)
    assert pet.tick(1000) == "idle"
    assert not pet.queue


def test_click_during_first_lie_down_does_not_start_supine_roll():
    pet = controller()
    pet.handle("supine", 0)
    pet.handle("click", 50)
    assert pet.tick(99) == "prone_enter"
    assert pet.tick(100) == "prone_exit"
    assert pet.tick(200) == "jumping"


def test_broken_action_reference_is_rejected_before_playback():
    clips = load_animations(resource_root())
    data = json.loads((resource_root() / "behaviors.json").read_text(encoding="utf-8"))
    data["actions"]["sleep"]["end"] = ["不存在的起身动作"]
    with pytest.raises(ValueError, match="动作阶段引用无效"):
        parse_behaviors(data, clips)


def test_random_jump_configuration_is_rejected():
    clips = load_animations(resource_root())
    data = json.loads((resource_root() / "behaviors.json").read_text(encoding="utf-8"))
    data["actions"]["scratch"]["start"] = ["jumping"]
    with pytest.raises(ValueError, match="不能加入随机行为"):
        parse_behaviors(data, clips)


def test_sleep_again_cancels_pending_wakeup_before_it_starts():
    pet = controller()
    pet.handle("sleep", 0)
    pet.tick(100)
    pet.handle("click", 110)
    pet.handle("sleep", 111)
    assert pet.tick(200) == "prone_sleep"
    assert not pet.queue


@pytest.mark.parametrize("field,value", [("anchor", [True, 241]), ("loop", "是"), ("stabilization", {"head_bottom": 168, "body_top": 128})])
def test_invalid_pose_configuration_reports_action_name(tmp_path, field, value):
    (tmp_path / "帧.png").touch()
    data = {"测试姿势": {"frames": ["帧.png"], "durations": [100], field: value}}
    (tmp_path / "animations.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="测试姿势"):
        load_animations(tmp_path)
