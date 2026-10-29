"""管理索食、喂食和逗猫的纯逻辑会话，不依赖窗口或真实输入。"""

import json
import random
from dataclasses import dataclass, fields
from enum import Enum
from pathlib import Path

from .pointer import look_direction


class PlayMode(str, Enum):
    NONE = "none"
    BEGGING = "begging"
    SERVING = "serving"
    EATING = "eating"
    SATISFIED = "satisfied"
    TEASER = "teaser"
    TEASER_SWIPE = "teaser_swipe"


@dataclass(frozen=True)
class PlayConfig:
    first_beg_ms: tuple[int, int]
    after_meal_ms: tuple[int, int]
    cancel_cooldown_ms: int
    serving_ms: tuple[int, int]
    eating_ms: tuple[int, int]
    satisfied_ms: tuple[int, int]
    beg_expressive_ms: tuple[int, int]
    beg_observe_ms: tuple[int, int]
    beg_sparse_ms: tuple[int, int]
    beg_clip_ms: int
    bubble_ms: tuple[int, int]
    bubble_gap_ms: int
    eat_enter_ms: int
    teaser_swipe_ms: int
    clips: dict[str, str]
    bubbles: dict[str, str]


def load_play_config(root):
    path = Path(root) / "play.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ValueError("缺少趣味互动配置：play.json") from error
    except (json.JSONDecodeError, UnicodeError) as error:
        raise ValueError("趣味互动配置无法读取：play.json") from error
    if not isinstance(data, dict):
        raise ValueError("趣味互动配置必须是对象")
    values = {}
    for field in fields(PlayConfig):
        if field.name in ("clips", "bubbles"):
            continue
        value = data.get(field.name)
        if field.type == tuple[int, int]:
            if not isinstance(value, list) or len(value) != 2 or any(type(item) is not int or item <= 0 for item in value) or value[0] > value[1]:
                raise ValueError(f"趣味互动时间范围无效：{field.name}")
            value = tuple(value)
        elif type(value) is not int or value <= 0:
            raise ValueError(f"趣味互动时间参数无效：{field.name}")
        values[field.name] = value
    clips = data.get("clips")
    roles = ("idle", "look", "beg_call", "beg_paw", "eat_enter", "eat_loop", "eat_exit", "teaser_ready", "teaser_left", "teaser_right", "teaser_swipe")
    if not isinstance(clips, dict) or any(not isinstance(clips.get(role), str) or not clips[role].strip() for role in roles):
        raise ValueError("趣味互动动画映射缺少必需角色或标识无效")
    try:
        available = json.loads((Path(root) / "animations.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, UnicodeError) as error:
        raise ValueError("趣味互动动画目录无法读取：animations.json") from error
    if not isinstance(available, dict) or any(clips[role] not in available for role in roles):
        raise ValueError("趣味互动动画引用不存在于动画目录")
    bubbles = data.get("bubbles")
    if not isinstance(bubbles, dict) or any(not isinstance(bubbles.get(role), str) or not bubbles[role].strip() for role in ("beg_snack", "beg_freeze_dried")):
        raise ValueError("趣味互动气泡文案缺失或无效")
    return PlayConfig(**values, clips=clips, bubbles=bubbles)


@dataclass(frozen=True)
class PlayView:
    mode: PlayMode
    clip: str
    clip_elapsed_ms: int
    look_index: int
    food: str | None
    bowl_level: int
    bubble: str | None
    toy_position: tuple[float, float] | None
    session_id: int
    origin: str | None
    session_elapsed_ms: int
    phase_elapsed_ms: int
    target_near: bool
    auto_due: bool
    auto_remaining_ms: int


class PlayController:
    def __init__(self, config, rng=None):
        self.config = config
        self.rng = rng if rng is not None else random.Random()
        self._id = 0
        self._mode = PlayMode.NONE
        self._clip = "idle"
        self._clip_elapsed = self._phase_elapsed = self._elapsed = 0
        self._last_tick = None
        self._last_flags = (False, True, False)
        self._auto_elapsed = 0
        self._auto_delay = self.rng.randint(*config.first_beg_ms)
        self._origin = self._food = self._bubble = self._toy_position = None
        self._look_index = 0
        self._target_near = False
        self._target_moved_at = 0
        self._first_bite = False
        self._completed = set()
        self._phase_duration = self._clip_duration = self._expressive_duration = 0
        self._next_paw = False
        self._bubble_until = 0
        self._last_bubble = -config.bubble_gap_ms

    @property
    def mode(self):
        return self._mode

    @property
    def session_id(self):
        return self._id

    @property
    def origin(self):
        return self._origin

    @property
    def view(self):
        bowl_level = 0
        if self._mode == PlayMode.SERVING:
            bowl_level = 3
        elif self._mode == PlayMode.EATING:
            bowl_level = max(0, 3 - self._phase_elapsed * 3 // self._phase_duration)
        return PlayView(
            self._mode, self.config.clips[self._clip], self._clip_elapsed, self._look_index,
            self._food, bowl_level, self._bubble, self._toy_position,
            self._id, self._origin, self._elapsed, self._phase_elapsed,
            self._target_near, self._auto_elapsed >= self._auto_delay,
            max(0, self._auto_delay - self._auto_elapsed),
        )

    def _set_clip(self, clip):
        self._clip = clip
        self._clip_elapsed = 0

    def _set_mode(self, mode, clip, duration=0):
        self._mode = mode
        self._phase_elapsed = 0
        self._phase_duration = duration
        self._set_clip(clip)

    def _cooldown_if_unfed(self):
        if self._mode in (PlayMode.BEGGING, PlayMode.SERVING, PlayMode.EATING) and not self._first_bite:
            self._auto_elapsed = 0
            self._auto_delay = max(self.config.cancel_cooldown_ms, self._auto_delay)

    def _begin(self, kind, now_ms, food, origin):
        self._cooldown_if_unfed()
        self._id += 1
        self._elapsed = self._phase_elapsed = self._clip_elapsed = 0
        if self._last_tick is None or now_ms > self._last_tick:
            self._last_tick = now_ms
        self._origin = origin
        self._food = food if kind in ("beg", "feed") else None
        self._bubble = self._toy_position = None
        self._target_near = False
        self._target_moved_at = 0
        self._first_bite = False
        self._completed.clear()
        self._last_bubble = -self.config.bubble_gap_ms
        if kind == "beg":
            self._set_mode(PlayMode.BEGGING, "beg_call")
            self._clip_duration = self.config.beg_clip_ms
            self._expressive_duration = self.rng.randint(*self.config.beg_expressive_ms)
            self._next_paw = True
            self._show_bubble()
        elif kind == "feed":
            self._serve()
        else:
            self._set_mode(PlayMode.TEASER, "teaser_ready")

    def request(self, kind, now_ms, food="freeze_dried"):
        if kind not in ("beg", "feed", "teaser"):
            raise ValueError(f"不支持的趣味互动：{kind}")
        if kind != "teaser" and food not in ("snack", "freeze_dried"):
            raise ValueError(f"不支持的食物：{food}")
        if kind == "feed" and self._mode == PlayMode.BEGGING:
            self.tick(now_ms, *self._last_flags)
            self._food = food
            self._serve()
        else:
            self._begin(kind, now_ms, food, "manual")
        return self.view

    def _serve(self):
        self._bubble = None
        self._set_mode(PlayMode.SERVING, "idle", self.rng.randint(*self.config.serving_ms))

    def click(self, now_ms):
        if self._mode == PlayMode.NONE:
            return False
        self.tick(now_ms, *self._last_flags)
        if self._mode == PlayMode.BEGGING:
            self._serve()
        elif self._mode == PlayMode.TEASER:
            self._set_mode(PlayMode.TEASER_SWIPE, "teaser_swipe", self.config.teaser_swipe_ms)
        return True

    def _show_bubble(self):
        if self._elapsed - self._last_bubble >= self.config.bubble_gap_ms:
            self._bubble = self.config.bubbles["beg_" + self._food]
            self._last_bubble = self._elapsed
            self._bubble_until = self._elapsed + self.rng.randint(*self.config.bubble_ms)

    def _tick_begging(self):
        if self._bubble is not None and self._elapsed >= self._bubble_until:
            self._bubble = None
        if self._clip_elapsed < self._clip_duration:
            return
        if self._clip != "idle":
            self._set_clip("idle")
            interval = self.config.beg_observe_ms if self._elapsed < self._expressive_duration else self.config.beg_sparse_ms
            self._clip_duration = self.rng.randint(*interval)
        else:
            self._set_clip("beg_paw" if self._next_paw else "beg_call")
            self._next_paw = not self._next_paw
            self._clip_duration = self.config.beg_clip_ms
            self._show_bubble()

    def _first_bite_started(self):
        if not self._first_bite:
            self._first_bite = True
            self._auto_elapsed = 0
            self._auto_delay = self.rng.randint(*self.config.after_meal_ms)

    def _teaser_clip(self):
        if not self._target_near:
            return "teaser_ready"
        if 2 <= self._look_index <= 6:
            return "teaser_right"
        if 10 <= self._look_index <= 14:
            return "teaser_left"
        return "look"

    def _tick_session(self, now_ms):
        if self._mode == PlayMode.BEGGING:
            self._tick_begging()
        elif self._mode == PlayMode.SERVING and self._phase_elapsed >= self._phase_duration:
            self._set_mode(PlayMode.EATING, "eat_enter", self.rng.randint(*self.config.eating_ms))
        elif self._mode == PlayMode.EATING:
            if not self._first_bite and self._phase_elapsed >= self.config.eat_enter_ms:
                self._first_bite_started()
                self._set_clip("eat_loop")
            if self._phase_elapsed >= self._phase_duration:
                self._set_mode(PlayMode.SATISFIED, "eat_exit", self.rng.randint(*self.config.satisfied_ms))
        elif self._mode == PlayMode.SATISFIED and self._phase_elapsed >= self._phase_duration:
            self.cancel(now_ms, "进食完成")
        elif self._mode == PlayMode.TEASER_SWIPE and self._phase_elapsed >= self._phase_duration:
            self._set_mode(PlayMode.TEASER, self._teaser_clip())
        if self._mode in (PlayMode.TEASER, PlayMode.TEASER_SWIPE) and self._target_near and self._elapsed - self._target_moved_at >= 3000:
            self._target_near = False
            if self._mode == PlayMode.TEASER:
                self._set_clip("teaser_ready")

    def tick(self, now_ms, auto_clock_running, session_running, can_auto_start):
        difference = 0 if self._last_tick is None else now_ms - self._last_tick
        if self._last_tick is None or now_ms > self._last_tick:
            self._last_tick = now_ms
        self._last_flags = (auto_clock_running, session_running, can_auto_start)
        delta = difference if 0 < difference <= 2000 else 0
        if self._mode == PlayMode.NONE:
            if auto_clock_running:
                self._auto_elapsed = min(self._auto_delay, self._auto_elapsed + delta)
                if self._auto_elapsed >= self._auto_delay and can_auto_start:
                    self._begin("beg", now_ms, "freeze_dried", "auto")
        elif session_running:
            self._elapsed += delta
            self._phase_elapsed += delta
            self._clip_elapsed += delta
            self._tick_session(now_ms)
        return self.view

    def set_target(self, position, center, width, now_ms):
        if self._mode not in (PlayMode.TEASER, PlayMode.TEASER_SWIPE):
            return self.view
        self.tick(now_ms, *self._last_flags)
        position = tuple(position)
        moved = position != self._toy_position
        self._toy_position = position
        dx, dy = position[0] - center[0], position[1] - center[1]
        distance_squared = dx * dx + dy * dy
        if self._target_near and distance_squared > (width * 1.5) ** 2:
            self._target_near = False
        if moved:
            self._target_moved_at = self._elapsed
            if distance_squared <= (width * 1.2) ** 2:
                self._target_near = True
        self._look_index = look_direction(dx, dy, self._look_index)
        if self._mode == PlayMode.TEASER:
            clip = self._teaser_clip()
            if clip != self._clip:
                self._set_clip(clip)
        return self.view

    def complete_clip(self, session_id, clip, now_ms):
        key = (session_id, clip)
        if session_id != self._id or clip != self.config.clips[self._clip] or key in self._completed or self._mode == PlayMode.NONE:
            return self.view
        self._completed.add(key)
        return self.tick(now_ms, *self._last_flags)

    def cancel(self, now_ms, reason):
        self._cooldown_if_unfed()
        self._id += 1
        self._set_mode(PlayMode.NONE, "idle")
        self._elapsed = 0
        self._origin = self._food = self._bubble = self._toy_position = None
        self._target_near = False
        self._completed.clear()
        if self._last_tick is None or now_ms > self._last_tick:
            self._last_tick = now_ms
        return self.view
