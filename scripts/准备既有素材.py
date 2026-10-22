"""复制已批准的透明帧，不改变原素材或逐帧缩放。"""

import json
import shutil
from pathlib import Path
from PIL import Image

root = Path(__file__).resolve().parents[1]
source = root / "资料/历史制作档案/源图与校验"
assets = root / "assets"
assets.mkdir(exist_ok=True)
clips = {}
for state in (source / "qa/frames").iterdir():
    if not state.is_dir():
        continue
    target = assets / "frames" / state.name
    shutil.copytree(state, target, dirs_exist_ok=True)
    for original in state.glob("*.png"):
        frame = Image.new("RGBA", (256, 256))
        frame.alpha_composite(Image.open(original).convert("RGBA"), (32, 40))
        frame.save(target / original.name)
    frames = [p.relative_to(assets).as_posix() for p in sorted(target.glob("*.png"))]
    clips[state.name] = {"frames": frames, "durations": [160 if state.name == "jumping" else 190] * len(frames)}
    if state.name == "idle":
        clips[state.name]["durations"] = [3200, 60, 60, 60, 80, 160]
        clips[state.name]["blend_ms"] = 60

atlas = Image.open(root / "资料/历史制作档案/成品与预览/安安精灵图.png")
target = assets / "frames/look"
target.mkdir(parents=True, exist_ok=True)
for i in range(16):
    x, y = i % 8 * 192, (9 + i // 8) * 208
    frame = Image.new("RGBA", (256, 256))
    frame.alpha_composite(atlas.crop((x, y, x + 192, y + 208)), (32, 40))
    frame.save(target / f"{i:02}.png")
clips["look"] = {"frames": [f"frames/look/{i:02}.png" for i in range(16)], "durations": [300] * 16}
(assets / "animations.json").write_text(json.dumps(clips, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("已准备", len(clips), "种已有动作。")
