"""带冷却、长睡眠和起卧过渡的纯 Python 状态机。"""

import random
from collections import deque


class BehaviorController:
    def __init__(self, durations, rng=None):
        self.durations = durations
        self.rng = rng or random.Random()
        self.state = "idle"
        self.started = 0
        self.next_action = 20000
        self.sleep_until = 0
        self.queue = deque()
        self.recent = deque(maxlen=2)
        self.dragging = False
        self.quiet = False

    def choose_action(self):
        options = [a for a in ("scratch", "wash", "yawn", "stretch", "look") if a in self.durations]
        if "prone_enter" in self.durations:
            options += ["sleep", "supine"]
        choices = [a for a in options if a not in self.recent] or options
        selected = self.rng.choice(choices) if choices else "idle"
        self.recent.append(selected)
        return selected

    def _start(self, state, now):
        self.state = state
        self.started = now
        if state.endswith("_sleep"):
            self.sleep_until = now + self.rng.randint(90000, 240000)
        if state == "idle":
            self.next_action = now + self.rng.randint(18000, 35000) * (4 if self.quiet else 1)

    def _wake_route(self):
        if self.state == "supine_exit":
            return ["prone_exit"]
        if self.state.startswith("supine"):
            return ["supine_exit", "prone_exit"]
        if self.state == "prone_exit":
            return []
        if self.state.startswith("prone"):
            return ["prone_exit"]
        return []

    def handle(self, event, now_ms):
        if event == "hover":
            return
        if event == "drag_start":
            self.dragging = True
            self.queue.clear()
            self._start("running-right", now_ms)
            return
        if event == "drag_end":
            self.dragging = False
            self.queue.clear()
            self._start("idle", now_ms)
            return
        if self.dragging:
            return
        if event == "click":
            if self.state == "jumping":
                return
            actions = ["jumping", "idle"]
        elif event in ("sleep", "supine"):
            actions = ["prone_enter"] + (["supine_enter", "supine_sleep"] if event == "supine" else ["prone_sleep"])
        elif event == "wake":
            actions = ["idle"]
        elif event in self.durations:
            actions = [event, "idle"]
        else:
            return
        actions = [a for a in actions if a in self.durations]
        if self.state.startswith(("prone", "supine")):
            self.queue = deque(self._wake_route() + actions)
        else:
            self.queue = deque(actions)
            if self.queue:
                self._start(self.queue.popleft(), now_ms)

    def tick(self, now_ms):
        if self.dragging:
            return self.state
        if self.state == "idle":
            if now_ms >= self.next_action:
                self.handle(self.choose_action(), now_ms)
        elif self.state.endswith("_sleep"):
            if self.queue:
                self._start(self.queue.popleft(), now_ms)
            elif now_ms >= self.sleep_until:
                self.handle("wake", now_ms)
        elif now_ms - self.started >= self.durations[self.state]:
            self._start(self.queue.popleft() if self.queue else "idle", now_ms)
        return self.state
