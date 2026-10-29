"""裁取内置图像工具生成的透明分镜，保留原图并写入运行序列。"""

import json
import runpy
from pathlib import Path
from PIL import Image

root = Path(__file__).resolve().parents[1]
assets = root / "assets"
clips = json.loads((assets / "animations.json").read_text(encoding="utf-8"))
for name in ("scratch", "prone", "supine", "daily"):
    source = Image.open(root / f"制作/新增动画/{name}-源图.png").convert("RGBA")
    assert source.size == (1536, 1024)
    target = assets / "frames" / name
    target.mkdir(parents=True, exist_ok=True)
    for i in range(6):
        x, y = i % 3 * 512, i // 3 * 512
        cell = source.crop((x, y, x + 512, y + 512))
        box = cell.getchannel("A").point(lambda a: 255 if a > 8 else 0).getbbox()
        assert box is not None
        cropped = cell.crop(box)
        resized = cropped.resize((round(cropped.width * .36), round(cropped.height * .36)), Image.Resampling.LANCZOS)
        frame = Image.new("RGBA", (256, 256))
        frame.alpha_composite(resized, ((256 - resized.width) // 2, 241 - resized.height))
        frame.save(target / f"{i:02}.png")


def register(key, source, indexes, durations):
    info = clips.setdefault(key, {"anchor": [128, 241], "loop": key in ("prone_sleep", "supine_sleep"), "transition_ms": 0 if key.startswith(("prone_", "supine_")) else 80})
    if any(path.startswith('frames/consistent/') for path in info.get('frames', [])):
        return
    info.update(frames=[f"frames/{source}/{i:02}.png" for i in indexes], durations=durations)


register("scratch", "scratch", [0, 1, 2, 3, 4, 3, 4, 5], [180, 180, 160, 140, 140, 140, 180, 220])
register("prone_enter", "prone", [0, 1, 2, 3, 4], [220, 260, 300, 360, 400])
register("prone_sleep", "prone", [4, 5], [1400, 1400])
register("prone_exit", "prone", [5, 4, 3, 2, 1, 0], [240, 200, 280, 280, 260, 240])
register("supine_enter", "supine", [0, 1, 2, 3], [320, 400, 450, 400])
register("supine_sleep", "supine", [3, 4], [1400, 1400])
register("supine_exit", "supine", [4, 3, 2, 5, 1, 0], [260, 240, 350, 350, 350, 320])
register("wash", "daily", [0, 1, 0, 1], [450, 500, 450, 500])
register("yawn", "daily", [2, 3, 2], [400, 650, 400])
register("stretch", "daily", [4, 5, 4], [550, 850, 550])
(assets / "animations.json").write_text(json.dumps(clips, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
preview_dir = root / "制作/新增动画/预览"
preview_dir.mkdir(exist_ok=True)
for key in ("scratch", "wash", "yawn", "stretch", "prone_enter", "prone_sleep", "supine_enter", "supine_sleep", "supine_exit"):
    info = clips[key]
    frames = []
    for path in info["frames"]:
        background = Image.new("RGBA", (256, 256), "#dceaff")
        background.alpha_composite(Image.open(assets / path))
        frames.append(background.convert("RGB"))
    frames[0].save(preview_dir / f"{key}.gif", save_all=True, append_images=frames[1:], duration=info["durations"], loop=0)
print("运行资源共", len(clips), "段动画，新增透明原帧 24 张。")
if (root / "制作/动画优化/挠耳连续分镜.png").is_file():
    runpy.run_path(str(root / "scripts/准备挠耳连续素材.py"), run_name="__main__")
