"""读取运行资源，源码和打包程序共用一套相对路径。"""

import json
import sys
from dataclasses import dataclass
from pathlib import Path


GROUND_ANCHOR = (123, 241)


@dataclass(frozen=True)
class Stabilization:
    body_top: int
    head_bottom: int | None = None
    eyes: tuple[tuple[int, int], ...] = ()
    radius: int = 14


@dataclass
class AnimationClip:
    frames: list[Path]
    durations: list[int]
    blend_ms: int = 0
    loop: bool = False
    anchor: tuple[int, int] = GROUND_ANCHOR
    transition_ms: int = 80
    stabilization: Stabilization | None = None

    @property
    def total_ms(self):
        return sum(self.durations)

    def frame_index(self, elapsed):
        return self.sample(elapsed)[0]

    def sample(self, elapsed):
        remaining = max(0, elapsed)
        remaining = remaining % self.total_ms if self.loop else min(remaining, self.total_ms - 1)
        for i, duration in enumerate(self.durations):
            if remaining < duration:
                following = min(i + 1, len(self.frames) - 1)
                blend = min(self.blend_ms, duration)
                amount = max(0, (remaining - duration + blend) / blend) if blend and following != i else 0
                return i, following, amount
            remaining -= duration
        return len(self.frames) - 1, len(self.frames) - 1, 0


def resource_root():
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "assets"
    return Path(__file__).resolve().parents[2] / "assets"


def load_animations(root):
    data = json.loads((root / "animations.json").read_text(encoding="utf-8"))
    clips = {}
    for key, info in data.items():
        frames = [root / p for p in info["frames"]]
        durations = info["durations"]
        if not frames or len(frames) != len(durations) or any(type(t) is not int or t <= 0 for t in durations):
            raise ValueError(f"动画时间参数无效：{key}")
        if any(not p.is_file() for p in frames):
            raise ValueError(f"缺少动画文件：{key}")
        blend_ms = info.get("blend_ms", 0)
        if type(blend_ms) is not int or blend_ms < 0:
            raise ValueError(f"动画过渡时间无效：{key}")
        loop = info.get("loop", False)
        anchor = info.get("anchor", list(GROUND_ANCHOR))
        transition_ms = info.get("transition_ms", 80)
        if type(loop) is not bool or not isinstance(anchor, list) or len(anchor) != 2 or any(type(n) is not int or not 0 <= n <= 256 for n in anchor):
            raise ValueError(f"动画循环或对齐位置无效：{key}")
        if type(transition_ms) is not int or not 0 <= transition_ms <= 500:
            raise ValueError(f"动作切换时间无效：{key}")
        stabilization = None
        if "stabilization" in info:
            policy = info["stabilization"]
            if not isinstance(policy, dict):
                raise ValueError(f"姿态稳定配置无效：{key}")
            body_top = policy.get("body_top")
            head_bottom = policy.get("head_bottom")
            eyes = policy.get("eyes", [])
            radius = policy.get("radius", 14)
            if type(body_top) is not int or not 0 < body_top <= 256:
                raise ValueError(f"固定身体区域无效：{key}")
            if head_bottom is not None and (type(head_bottom) is not int or not 0 <= head_bottom < body_top):
                raise ValueError(f"完整头部区域无效：{key}")
            if not isinstance(eyes, list) or any(not isinstance(p, list) or len(p) != 2 or any(type(n) is not int or not 0 <= n < 256 for n in p) for p in eyes):
                raise ValueError(f"眼睛区域无效：{key}")
            if type(radius) is not int or not 1 <= radius <= 64 or bool(eyes) == (head_bottom is not None):
                raise ValueError(f"姿态稳定配置无效：{key}")
            stabilization = Stabilization(body_top, head_bottom, tuple(map(tuple, eyes)), radius)
        clips[key] = AnimationClip(frames, durations, blend_ms, loop, tuple(anchor), transition_ms, stabilization)
    return clips
