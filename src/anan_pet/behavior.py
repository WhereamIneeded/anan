"""从配置读取动作阶段、冷却和随机权重的纯 Python 状态机。"""

import json
import random
from collections import deque
from dataclasses import dataclass

from .animation import resource_root


@dataclass(frozen=True)
class ActionSpec:
    label: str
    start: tuple[str, ...]
    loop: str | None
    end: tuple[str, ...]
    hold_ms: tuple[int, int]
    weight: int
    cooldown_ms: int


@dataclass(frozen=True)
class BehaviorConfig:
    actions: dict[str, ActionSpec]
    exits: dict[str, tuple[str, ...]]
    phases: dict[str, str]
    idle_interval: tuple[int, int]
    quiet_multiplier: int
    attention_grace_ms: int


def interval(value, label):
    if not isinstance(value, list) or len(value) != 2 or any(type(n) is not int or n <= 0 for n in value) or value[0] > value[1]:
        raise ValueError(f"行为时间范围无效：{label}")
    return tuple(value)


def parse_behaviors(data, available):
    if not isinstance(data, dict):
        raise ValueError("行为配置必须是对象")
    idle_interval = interval(data.get("idle_interval_ms"), "待机间隔")
    quiet = data.get("quiet_multiplier", 4)
    grace = data.get("attention_grace_ms", 5000)
    if type(quiet) is not int or quiet < 1 or type(grace) is not int or grace < 0:
        raise ValueError("安静模式或交互间隔无效")
    actions, exits, phases = {}, {}, {"idle": "idle"}
    definitions = data.get("actions")
    if not isinstance(definitions, dict) or not definitions:
        raise ValueError("缺少动作定义")
    for name, info in definitions.items():
        if not isinstance(info, dict) or not isinstance(name, str):
            raise ValueError("动作定义无效")
        label = info.get("label", name)
        if not isinstance(label, str) or not label.strip():
            raise ValueError(f"动作显示名称无效：{name}")
        start, end, loop = info.get("start", []), info.get("end", []), info.get("loop")
        if any(not isinstance(v, list) or any(not isinstance(s, str) or s not in available for s in v) for v in (start, end)) or not start:
            raise ValueError(f"动作阶段引用无效：{name}")
        if loop is not None and (not isinstance(loop, str) or loop not in available or len(start) != len(end)):
            raise ValueError(f"循环动作的起卧阶段不匹配：{name}")
        if loop is not None and not getattr(available[loop], "loop", True):
            raise ValueError(f"保持阶段必须使用循环动画：{name}")
        weight, cooldown = info.get("weight", 0), info.get("cooldown_ms", 0)
        if any(type(n) is not int or n < 0 for n in (weight, cooldown)):
            raise ValueError(f"动作权重或冷却无效：{name}")
        if weight and "jumping" in (*start, *end, loop):
            raise ValueError("跳跃只能由单击或手动操作触发，不能加入随机行为")
        hold = interval(info.get("hold_ms"), name) if loop else (0, 0)
        actions[name] = ActionSpec(label, tuple(start), loop, tuple(end), hold, weight, cooldown)
        if loop:
            routes = {state: tuple(end[-(i + 1):]) for i, state in enumerate(start)}
            routes[loop] = tuple(end)
            routes.update({state: tuple(end[i + 1:]) for i, state in enumerate(end)})
            for state, route in routes.items():
                if state in exits and exits[state] != route:
                    raise ValueError(f"共享姿势的退出路线冲突：{state}")
                exits[state] = route
            phases.update({state: "start" for state in start})
            phases[loop] = "loop"
            phases.update({state: "end" for state in end})
    return BehaviorConfig(actions, exits, phases, idle_interval, quiet, grace)


def load_behaviors(root, available):
    return parse_behaviors(json.loads((root / "behaviors.json").read_text(encoding="utf-8")), available)


class BehaviorController:
    def __init__(self, durations, rng=None, config=None):
        self.durations = durations
        self.rng = rng or random.Random()
        self.config = config or load_behaviors(resource_root(), durations)
        self.state = "idle"
        self.started = 0
        self.next_action = self.rng.randint(*self.config.idle_interval)
        self.sleep_until = 0
        self.queue = deque()
        self.recent = deque(maxlen=2)
        self.last_used = {}
        self.requested_action = "idle"
        self.dragging = False
        self.quiet = False
        self.loop_actions = {spec.loop: spec for spec in self.config.actions.values() if spec.loop}

    @property
    def phase(self):
        return "drag" if self.dragging else self.config.phases.get(self.state, "action")

    def choose_action(self, now_ms=0):
        options = [name for name, spec in self.config.actions.items() if spec.weight > 0 and now_ms - self.last_used.get(name, -spec.cooldown_ms) >= spec.cooldown_ms]
        choices = [name for name in options if name not in self.recent] or options
        if not choices:
            return "idle"
        selected = self.rng.choices(choices, weights=[self.config.actions[name].weight for name in choices], k=1)[0]
        self.recent.append(selected)
        return selected

    def _start(self, state, now):
        self.state = state
        self.started = now
        if state in self.loop_actions:
            self.sleep_until = now + self.rng.randint(*self.loop_actions[state].hold_ms)
        if state == "idle":
            self.next_action = now + self.rng.randint(*self.config.idle_interval) * (self.config.quiet_multiplier if self.quiet else 1)
            self.requested_action = "idle"

    def set_drag_direction(self, direction, now_ms):
        state = "running-" + direction
        if self.dragging and state in self.durations and self.state != state:
            self._start(state, now_ms)

    def handle(self, event, now_ms):
        if event == "hover":
            if self.state == "idle" and not self.dragging:
                self.next_action = max(self.next_action, now_ms + self.config.attention_grace_ms)
            return
        if event in ("drag_start", "drag_end"):
            self.dragging = event == "drag_start"
            self.queue.clear()
            self.requested_action = "idle"
            self._start("running-right" if self.dragging else "idle", now_ms)
            return
        if self.dragging:
            return
        if event == "click":
            if self.state == "jumping":
                return
            event = "jumping"
        if event in self.config.actions:
            spec = self.config.actions[event]
            if spec.loop and self.state == spec.loop:
                self.queue.clear()
                self.requested_action = event
                return
            if spec.loop and event == self.requested_action and self.state in (*spec.start, spec.loop):
                return
            actions = list(spec.start) + ([spec.loop] if spec.loop else list(spec.end) + ["idle"])
            self.last_used[event] = now_ms
        elif event in ("wake", "idle"):
            actions = ["idle"]
        elif event in self.durations:
            actions = [event, "idle"]
        else:
            return
        self.requested_action = event
        if self.state in self.config.exits:
            self.queue = deque(list(self.config.exits[self.state]) + actions)
        else:
            self.queue = deque(actions)
            self._start(self.queue.popleft(), now_ms)

    def tick(self, now_ms):
        if self.dragging:
            return self.state
        if self.state == "idle":
            if now_ms >= self.next_action:
                self.handle(self.choose_action(now_ms), now_ms)
        elif self.state in self.loop_actions:
            if self.queue:
                self._start(self.queue.popleft(), now_ms)
            elif now_ms >= self.sleep_until:
                self.handle("wake", now_ms)
        elif now_ms - self.started >= self.durations[self.state]:
            self._start(self.queue.popleft() if self.queue else "idle", now_ms)
        return self.state
