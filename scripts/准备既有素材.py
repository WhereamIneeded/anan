"""从最终去绿边图集提取运行帧，保留原素材和现有播放配置。"""

import json
from pathlib import Path
from PIL import Image

root = Path(__file__).resolve().parents[1]
assets = root / "assets"
assets.mkdir(exist_ok=True)
config = assets / "animations.json"
clips = json.loads(config.read_text(encoding="utf-8")) if config.exists() else {}
atlas = Image.open(root / "资料/历史制作档案/成品与预览/安安精灵图.png").convert("RGBA")
states = (("idle", 6), ("running-right", 8), ("running-left", 8), ("waving", 4), ("jumping", 5), ("failed", 8), ("waiting", 6), ("running", 6), ("review", 6))
for row, (name, count) in enumerate(states):
    target = assets / "frames" / name
    target.mkdir(parents=True, exist_ok=True)
    for i in range(count):
        frame = Image.new("RGBA", (256, 256))
        frame.alpha_composite(atlas.crop((i * 192, row * 208, (i + 1) * 192, (row + 1) * 208)), (32, 40))
        frame.save(target / f"{i:02}.png")
    if name not in clips:
        clips[name] = {"frames": [f"frames/{name}/{i:02}.png" for i in range(count)], "durations": [160 if name == "jumping" else 190] * count, "anchor": [123, 241], "loop": name in ("idle", "running-left", "running-right"), "transition_ms": 80}
        if name == "idle":
            clips[name].update(durations=[3200, 60, 60, 60, 80, 160], blend_ms=60)
            clips[name]["stabilization"] = {"body_top": 128, "eyes": [[108, 106], [137, 106]], "radius": 14}

target = assets / "frames/look"
target.mkdir(parents=True, exist_ok=True)
for i in range(16):
    x, y = i % 8 * 192, (9 + i // 8) * 208
    frame = Image.new("RGBA", (256, 256))
    frame.alpha_composite(atlas.crop((x, y, x + 192, y + 208)), (32, 40))
    frame.save(target / f"{i:02}.png")
clips.setdefault("look", {"frames": [f"frames/look/{i:02}.png" for i in range(16)], "durations": [300] * 16, "anchor": [123, 241], "loop": True, "transition_ms": 70, "stabilization": {"body_top": 168, "head_bottom": 152}})
config.write_text(json.dumps(clips, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("已准备", len(clips), "种已有动作。")
