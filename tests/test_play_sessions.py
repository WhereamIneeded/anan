from dataclasses import replace
from pathlib import Path
import json
import random

import pytest

from anan_pet.play import PlayController, PlayMode, load_play_config


ROOT = Path(__file__).resolve().parents[1] / "assets"


def make_controller(**changes):
    return PlayController(replace(load_play_config(ROOT), **changes), random.Random(7))


def step(controller, start, end, **flags):
    options = dict(auto_clock_running=True, session_running=True, can_auto_start=True)
    options.update(flags)
    for now in range(start, end + 1, 1000):
        controller.tick(now, **options)
    return controller.view


def test_配置包含已批准的时间范围():
    config = load_play_config(ROOT)
    assert config.first_beg_ms == (1200000, 2400000)
    assert config.after_meal_ms == (3600000, 5400000)
    assert config.cancel_cooldown_ms >= 1800000
    assert config.serving_ms == (1000, 2000)
    assert config.eating_ms == (12000, 20000)
    assert config.satisfied_ms == (3000, 5000)


@pytest.mark.parametrize("value", [[2, 1], [0, 3], [True, 3], [1], "错误"])
def test_非法配置范围给出中文错误(tmp_path, value):
    data = json.loads((ROOT / "play.json").read_text(encoding="utf-8"))
    data["first_beg_ms"] = value
    (tmp_path / "play.json").write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="范围无效"):
        load_play_config(tmp_path)


def test_缺少配置给出中文错误(tmp_path):
    with pytest.raises(ValueError, match="缺少趣味互动配置"):
        load_play_config(tmp_path)


def test_索食二十分钟不自动结束():
    controller = make_controller()
    controller.request("beg", 0)
    old_id = controller.view.session_id
    view = step(controller, 0, 1200000)
    assert view.mode == PlayMode.BEGGING
    assert view.session_id == old_id
    assert view.origin == "manual"


def test_两次点击只投放一份且停止后恢复普通点击():
    controller = make_controller()
    controller.request("beg", 0)
    session_id = controller.view.session_id
    assert controller.click(100)
    assert controller.click(200)
    assert controller.view.mode == "serving"
    assert controller.view.session_id == session_id
    controller.cancel(300, "停止当前互动")
    assert controller.view.mode == "none"
    assert controller.view.session_id != session_id
    assert controller.view.bowl_level == 0
    assert controller.view.bubble is None
    assert not controller.click(400)


def test_旧进食完成信号不能改变新逗猫会话():
    controller = make_controller(serving_ms=(1000, 1000))
    controller.request("feed", 0, food="snack")
    step(controller, 0, 2000)
    old_id = controller.view.session_id
    controller.request("teaser", 2000)
    current = controller.view
    controller.complete_clip(old_id, "eat_loop", 2100)
    assert controller.view == current


def test_首次自动索食只计算清醒可见的累计时间():
    controller = make_controller(first_beg_ms=(3000, 3000))
    step(controller, 0, 2000)
    assert controller.view.mode == "none"
    step(controller, 3000, 9000, auto_clock_running=False)
    assert controller.view.mode == "none"
    controller.tick(10000, True, True, True)
    assert controller.view.mode == "begging"
    assert controller.view.origin == "auto"


def test_忙时保留一个到期资格且不会排队补发():
    controller = make_controller(first_beg_ms=(2000, 2000))
    step(controller, 0, 100000, can_auto_start=False)
    assert controller.view.mode == "none"
    assert controller.view.auto_due
    controller.tick(101000, True, True, True)
    session_id = controller.view.session_id
    step(controller, 102000, 110000)
    assert controller.view.session_id == session_id


def test_时间倒退和超过两秒跳变不累积或补发():
    controller = make_controller(first_beg_ms=(3000, 3000))
    controller.tick(1000, True, True, True)
    controller.tick(2000, True, True, True)
    controller.tick(1000, True, True, True)
    controller.tick(1000000, True, True, True)
    assert controller.view.auto_remaining_ms == 2000
    controller.tick(1001000, True, True, True)
    assert controller.view.auto_remaining_ms == 1000
    controller.tick(1003000, True, True, True)
    assert controller.view.mode == "begging"


def test_暂停会话不推进投放进食及气泡时间():
    controller = make_controller(serving_ms=(1000, 1000))
    controller.request("feed", 0)
    step(controller, 0, 10000, session_running=False)
    assert controller.view.mode == "serving"
    assert controller.view.phase_elapsed_ms == 0
    controller.tick(11000, False, True, False)
    assert controller.view.mode == "eating"


def test_投放进食满足无需动画回调也能全部结束():
    controller = make_controller(serving_ms=(1000, 1000), eating_ms=(12000, 12000), satisfied_ms=(3000, 3000))
    controller.request("feed", 0, food="snack")
    assert controller.view.food == "snack"
    assert controller.view.bowl_level == 3
    step(controller, 0, 1000)
    assert controller.view.mode == "eating"
    assert controller.view.clip == "eat_enter"
    step(controller, 2000, 4000)
    assert controller.view.clip == "eat_loop"
    assert controller.view.bowl_level in (1, 2, 3)
    step(controller, 5000, 13000)
    assert controller.view.mode == "satisfied"
    assert controller.view.clip == "eat_exit"
    assert controller.view.clip_elapsed_ms == 0
    assert controller.view.bowl_level == 0
    step(controller, 14000, 16000)
    assert controller.view.mode == "none"


def test_第一口只结算一次且吃后取消不改已抽取的间隔():
    controller = make_controller(serving_ms=(1000, 1000), after_meal_ms=(5000, 5000), cancel_cooldown_ms=3000)
    controller.request("feed", 0)
    step(controller, 0, 1000)
    assert controller.view.auto_remaining_ms != 5000
    step(controller, 2000, 3000)
    assert controller.view.auto_remaining_ms == 5000
    step(controller, 4000, 5000)
    assert controller.view.auto_remaining_ms == 5000
    controller.complete_clip(controller.view.session_id, "eat_enter", 5000)
    controller.cancel(5000, "停止当前互动")
    assert controller.view.auto_remaining_ms == 5000
    step(controller, 6000, 9000)
    assert controller.view.mode == "none"
    controller.tick(10000, True, True, True)
    assert controller.view.mode == "begging"


def test_未吃就取消会重新冷却且其他玩法不累积索食时间():
    controller = make_controller(first_beg_ms=(1000, 1000), cancel_cooldown_ms=3000)
    step(controller, 0, 1000)
    controller.cancel(1000, "切换动作")
    assert controller.view.auto_remaining_ms == 3000
    controller.request("teaser", 1000)
    step(controller, 2000, 10000)
    assert controller.view.auto_remaining_ms == 3000
    controller.cancel(10000, "停止当前互动")
    step(controller, 11000, 12000)
    assert controller.view.mode == "none"
    controller.tick(13000, True, True, True)
    assert controller.view.mode == "begging"


def test_索食包含观察停顿且后期表达间隔更长():
    controller = make_controller(beg_expressive_ms=(3000, 3000), beg_observe_ms=(1000, 1000), beg_sparse_ms=(5000, 5000), beg_clip_ms=1000)
    controller.request("beg", 0)
    assert controller.view.clip == "beg_call"
    controller.tick(1000, False, True, False)
    assert controller.view.clip == "idle"
    controller.tick(2000, False, True, False)
    assert controller.view.clip == "beg_paw"
    controller.tick(3000, False, True, False)
    assert controller.view.clip == "idle"
    step(controller, 4000, 7000)
    assert controller.view.clip == "idle"
    controller.tick(8000, False, True, False)
    assert controller.view.clip == "beg_call"
    assert controller.view.clip_elapsed_ms == 0


def test_索食气泡三到五秒消失且至少间隔二十秒():
    controller = make_controller(bubble_ms=(3000, 3000), bubble_gap_ms=20000, beg_clip_ms=1000, beg_observe_ms=(1000, 1000))
    controller.request("beg", 0)
    assert controller.view.bubble == "喵～想吃冻干，点我喂一份"
    step(controller, 0, 3000)
    assert controller.view.bubble is None
    for now in range(4000, 20000, 1000):
        controller.tick(now, False, True, False)
        assert controller.view.bubble is None
    controller.tick(20000, False, True, False)
    assert controller.view.bubble is not None


def test_逗猫距离滞回及静止等待会保留玩具():
    controller = make_controller()
    controller.request("teaser", 0)
    controller.set_target((100, 0), (0, 0), 100, 0)
    assert controller.view.target_near
    assert controller.view.look_index == 4
    controller.set_target((140, 0), (0, 0), 100, 100)
    assert controller.view.target_near
    controller.set_target((151, 0), (0, 0), 100, 200)
    assert not controller.view.target_near
    controller.set_target((120, 0), (0, 0), 100, 300)
    assert controller.view.target_near
    step(controller, 1000, 4000)
    assert controller.view.mode == "teaser"
    assert controller.view.clip == "teaser_ready"
    assert controller.view.toy_position == (120, 0)


def test_单击拍击不叠加并自动回到逗猫():
    controller = make_controller(teaser_swipe_ms=1000)
    controller.request("teaser", 0)
    controller.set_target((-30, -30), (0, 0), 100, 0)
    assert controller.click(100)
    session_id = controller.view.session_id
    assert controller.view.mode == "teaser_swipe"
    controller.tick(500, False, True, False)
    elapsed = controller.view.clip_elapsed_ms
    assert controller.click(500)
    assert controller.view.clip_elapsed_ms == elapsed
    controller.tick(1100, False, True, False)
    assert controller.view.mode == "teaser"
    assert controller.view.session_id == session_id


def test_重复完成信号不重复推进且取消信号失效():
    controller = make_controller(teaser_swipe_ms=1000)
    controller.request("teaser", 0)
    controller.click(0)
    session_id = controller.view.session_id
    controller.complete_clip(session_id, "teaser_swipe", 1000)
    current = controller.view
    controller.complete_clip(session_id, "teaser_swipe", 1000)
    assert controller.view == current
    controller.cancel(1000, "停止当前互动")
    current = controller.view
    controller.complete_clip(session_id, "teaser_ready", 1100)
    assert controller.view == current


def test_一百次召唤替换旧会话而不积压():
    controller = make_controller()
    for number in range(100):
        controller.request("teaser", number)
        controller.set_target((number, 0), (0, 0), 100, number)
        assert controller.view.session_id == number + 1
    assert controller.view.toy_position == (99, 0)
    controller.cancel(100, "停止当前互动")
    step(controller, 1000, 10000)
    assert controller.view.mode == "none"


@pytest.mark.parametrize("kind,food", [("错误", "freeze_dried"), ("feed", "错误")])
def test_无效请求给出中文错误(kind, food):
    controller = make_controller()
    with pytest.raises(ValueError, match="不支持"):
        controller.request(kind, 0, food)


def test_单击从实际投放时间开始计时():
    controller = make_controller(serving_ms=(1000, 1000))
    controller.request("beg", 0)
    controller.tick(500, False, True, False)
    controller.click(900)
    controller.tick(1000, False, True, False)
    assert controller.view.mode == "serving"
    assert controller.view.phase_elapsed_ms == 100
    assert controller.view.clip_elapsed_ms == 100


def test_索食转手动喂食沿用会话且从请求时刻计时():
    controller = make_controller(serving_ms=(1000, 1000))
    controller.request("beg", 0)
    session_id = controller.view.session_id
    controller.request("feed", 900, "snack")
    controller.tick(1000, False, True, False)
    assert controller.view.session_id == session_id
    assert controller.view.food == "snack"
    assert controller.view.phase_elapsed_ms == 100


def test_拍击从单击时刻开始而非上一帧时间():
    controller = make_controller(teaser_swipe_ms=1000)
    controller.request("teaser", 0)
    controller.tick(500, False, True, False)
    controller.click(900)
    controller.tick(1000, False, True, False)
    assert controller.view.clip_elapsed_ms == 100
    controller.tick(1900, False, True, False)
    assert controller.view.mode == "teaser"


def test_时间倒退后恢复原时刻不会重复计时():
    controller = make_controller(first_beg_ms=(3000, 3000))
    controller.tick(1000, True, True, True)
    controller.tick(2000, True, True, True)
    controller.tick(1500, True, True, True)
    controller.tick(2000, True, True, True)
    assert controller.view.auto_remaining_ms == 2000


def test_玩具静止三秒从最近移动时刻开始():
    controller = make_controller()
    controller.request("teaser", 0)
    controller.tick(1000, False, True, False)
    controller.set_target((100, 0), (0, 0), 100, 1500)
    controller.tick(3000, False, True, False)
    controller.tick(4000, False, True, False)
    assert controller.view.target_near
    controller.tick(4500, False, True, False)
    assert controller.view.clip == "teaser_ready"


def test_当前拍击完成能推进且保留同一会话():
    controller = make_controller(teaser_swipe_ms=1000)
    controller.request("teaser", 0)
    session_id = controller.view.session_id
    controller.click(0)
    controller.complete_clip(session_id, "teaser_swipe", 1000)
    assert controller.view.mode == "teaser"
    assert controller.view.session_id == session_id


@pytest.mark.parametrize("food", ["不属于食物的参数", None, object()])
def test_逗猫忽略任意食物参数(food):
    controller = make_controller()
    controller.request("teaser", 0, food=food)
    assert controller.view.mode == "teaser"
    assert controller.view.food is None


def test_低头完成开始吃第一口才结算吃后间隔():
    controller = make_controller(first_beg_ms=(1200000, 1200000), after_meal_ms=(3600000, 3600000), serving_ms=(1000, 1000), eat_enter_ms=1200)
    controller.request("feed", 0)
    controller.tick(1000, False, True, False)
    assert controller.view.clip == "eat_enter"
    assert controller.view.auto_remaining_ms == 1200000
    controller.tick(2199, False, True, False)
    assert controller.view.clip == "eat_enter"
    assert controller.view.auto_remaining_ms == 1200000
    controller.tick(2200, False, True, False)
    assert controller.view.clip == "eat_loop"
    assert controller.view.auto_remaining_ms == 3600000
    assert controller.view.clip_elapsed_ms == 0


def test_已低头尚未吃第一口时取消仍冷却三十分钟():
    controller = make_controller(first_beg_ms=(1200000, 1200000), after_meal_ms=(3600000, 3600000), cancel_cooldown_ms=1800000, serving_ms=(1000, 1000))
    controller.request("feed", 0)
    controller.tick(1000, False, True, False)
    assert controller.view.mode == "eating"
    assert controller.view.clip == "eat_enter"
    controller.cancel(1100, "停止当前互动")
    assert controller.view.auto_remaining_ms == 1800000


def test_倒退的取消时间不降低累计时钟高水位():
    controller = make_controller(first_beg_ms=(1200000, 1200000), cancel_cooldown_ms=1800000)
    controller.request("beg", 1000)
    controller.tick(2000, False, True, False)
    controller.cancel(1500, "停止当前互动")
    controller.tick(2000, True, True, True)
    assert controller.view.auto_remaining_ms == 1800000


def test_倒退的新请求时间不降低会话时钟高水位():
    controller = make_controller()
    controller.request("beg", 1000)
    controller.tick(2000, False, True, False)
    controller.request("teaser", 1500)
    controller.tick(2000, True, True, True)
    assert controller.view.session_elapsed_ms == 0
    assert controller.view.clip_elapsed_ms == 0


def test_计划样例可直接读取只读会话属性():
    controller = make_controller()
    assert controller.mode == "none"
    controller.request("beg", 0)
    assert controller.mode == "begging"
    assert controller.origin == "manual"
    session_id = controller.session_id
    controller.click(0)
    assert controller.mode == "serving"
    assert controller.session_id == session_id
    for name in ("mode", "session_id", "origin"):
        with pytest.raises(AttributeError):
            setattr(controller, name, "禁止修改")


def temporary_config(root):
    roles = ("idle", "look", "beg_call", "beg_paw", "eat_enter", "eat_loop", "eat_exit", "teaser_ready", "teaser_left", "teaser_right", "teaser_swipe")
    data = json.loads((ROOT / "play.json").read_text(encoding="utf-8"))
    data["clips"] = {role: "配置动画_" + role for role in roles}
    data["bubbles"] = {"beg_snack": "请给安安一份零食", "beg_freeze_dried": "请给安安一份冻干"}
    (root / "play.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    (root / "animations.json").write_text(json.dumps({name: {} for name in data["clips"].values()}), encoding="utf-8")
    return data


def test_动画映射及两种气泡实际使用配置而不硬编码(tmp_path):
    data = temporary_config(tmp_path)
    config = load_play_config(tmp_path)
    controller = PlayController(replace(config, serving_ms=(1000, 1000), eat_enter_ms=1000), random.Random(7))
    controller.request("beg", 0, "snack")
    assert controller.view.clip == data["clips"]["beg_call"]
    assert controller.view.bubble == "请给安安一份零食"
    controller.request("beg", 0, "freeze_dried")
    assert controller.view.bubble == "请给安安一份冻干"
    controller.click(0)
    assert controller.view.clip == data["clips"]["idle"]
    controller.tick(1000, False, True, False)
    assert controller.view.clip == data["clips"]["eat_enter"]
    controller.tick(2000, False, True, False)
    assert controller.view.clip == data["clips"]["eat_loop"]
    controller.request("teaser", 2000)
    assert controller.view.clip == data["clips"]["teaser_ready"]
    controller.click(2000)
    controller.complete_clip(controller.session_id, data["clips"]["teaser_swipe"], 3000)
    assert controller.mode == "teaser"


def test_缺少必需动画角色报错(tmp_path):
    data = temporary_config(tmp_path)
    del data["clips"]["eat_loop"]
    (tmp_path / "play.json").write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="动画映射"):
        load_play_config(tmp_path)


def test_动画映射不能引用不存在的动画键(tmp_path):
    data = temporary_config(tmp_path)
    animations = {name: {} for name in data["clips"].values() if name != data["clips"]["eat_loop"]}
    (tmp_path / "animations.json").write_text(json.dumps(animations), encoding="utf-8")
    with pytest.raises(ValueError, match="动画引用"):
        load_play_config(tmp_path)


def test_缺少动画目录报中文错误(tmp_path):
    temporary_config(tmp_path)
    (tmp_path / "animations.json").unlink()
    with pytest.raises(ValueError, match="动画目录"):
        load_play_config(tmp_path)


def test_空气泡文案报中文错误(tmp_path):
    data = temporary_config(tmp_path)
    data["bubbles"]["beg_snack"] = "  "
    (tmp_path / "play.json").write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="气泡文案"):
        load_play_config(tmp_path)
