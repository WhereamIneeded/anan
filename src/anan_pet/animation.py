"""读取运行资源，源码和打包程序共用一套相对路径。"""

import json
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass
class AnimationClip:
    frames: list[Path]
    durations: list[int]
    blend_ms: int = 0
    loop: bool = False

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
        clips[key] = AnimationClip(frames, durations, blend_ms, key in ("idle", "look", "prone_sleep", "supine_sleep"))
    return clips
