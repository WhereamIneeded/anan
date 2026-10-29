"""清除极低透明度噪点，按完整主体提取十六帧并对齐白色前爪。"""

import argparse
import json
from pathlib import Path

from PIL import Image


def find_subjects(source):
    width, height = source.size
    alpha = source.getchannel("A").tobytes()
    remaining = bytearray(value > 8 for value in alpha)
    subjects = []
    for start in range(width * height):
        if not remaining[start]:
            continue
        remaining[start] = 0
        pending = [start]
        points = []
        while pending:
            index = pending.pop()
            points.append(index)
            x, y = index % width, index // width
            for ny in range(max(0, y - 1), min(height, y + 2)):
                for nx in range(max(0, x - 1), min(width, x + 2)):
                    neighbor = ny * width + nx
                    if remaining[neighbor]:
                        remaining[neighbor] = 0
                        pending.append(neighbor)
        xs = [index % width for index in points]
        ys = [index // width for index in points]
        subjects.append({
            "points": points,
            "box": (min(xs), min(ys), max(xs) + 1, max(ys) + 1),
            "center": (sum(xs) / len(xs), sum(ys) / len(ys)),
        })
    assert len(subjects) == 16, f"清理后应有十六个独立猫咪主体，实际为{len(subjects)}个"
    subjects.sort(key=lambda subject: subject["center"][1])
    # 分镜未严格落在等分格内，先按质心分行，再按横向位置排序。
    return [subject for row in range(4) for subject in sorted(subjects[row * 4:row * 4 + 4], key=lambda item: item["center"][0])]


def paw_anchor(source, subject, strip_height=6):
    pixels = source.load()
    box = subject["box"]
    bottom = box[3] - (box[3] - box[1]) * 0.2
    white = []
    for index in subject["points"]:
        x, y = index % source.width, index // source.width
        if y < bottom:
            continue
        red, green, blue, alpha = pixels[x, y]
        if alpha >= 128 and min(red, green, blue) >= 175 and max(red, green, blue) - min(red, green, blue) <= 65:
            white.append((x, y))
    assert white, "主体下部缺少可识别的白色前爪"
    floor = max(y for _, y in white)
    strip = [x for x, y in white if y > floor - strip_height]
    # 使用落地白爪的跨度中心，不受抬起的后爪和浓棕尾巴影响。
    return (min(strip) + max(strip) + 1) / 2, floor + 1


def prepare_frames(root):
    source_path = root / "制作/动画优化/挠耳连续分镜.png"
    source = Image.open(source_path).convert("RGBA")
    subjects = find_subjects(source)
    cleaned = source.copy()
    noise = source.getchannel("A").point(lambda value: 255 if value <= 8 else 0)
    cleaned.paste((0, 0, 0, 0), (0, 0), noise)
    cleaned.save(source_path.with_stem(source_path.stem + "-透明清理"))
    first_box = subjects[0]["box"]
    scale = 173 / (first_box[3] - first_box[1])
    target = root / "assets/frames/scratch-v2"
    target.mkdir(parents=True, exist_ok=True)
    report = []
    for index, subject in enumerate(subjects):
        box = subject["box"]
        padded = (max(0, box[0] - 2), max(0, box[1] - 2), min(source.width, box[2] + 2), min(source.height, box[3] + 2))
        cell = cleaned.crop(padded)
        resized = cell.resize((round(cell.width * scale), round(cell.height * scale)), Image.Resampling.LANCZOS)
        resized_subject = {"box": resized.getchannel("A").getbbox(), "points": [pixel for pixel, alpha in enumerate(resized.getchannel("A").tobytes()) if alpha > 8]}
        # 缩放后再量一次前爪，消除取整和重采样造成的一像素基线差。
        paw_x, paw_y = paw_anchor(resized, resized_subject, strip_height=4)
        offset_x = round(123 - paw_x)
        offset_y = 241 - paw_y
        assert 0 <= offset_x and offset_x + resized.width <= 256, f"第{index + 1}帧横向超出画布"
        assert 0 <= offset_y and offset_y + resized.height <= 256, f"第{index + 1}帧纵向超出画布"
        frame = Image.new("RGBA", (256, 256))
        frame.alpha_composite(resized, (offset_x, offset_y))
        frame.save(target / f"{index:02}.png")
        report.append({"帧": index + 1, "源主体边界": box, "成品前爪中心与底边": [paw_x + offset_x, paw_y + offset_y], "成品边界": frame.getchannel("A").getbbox()})
    return {"帧数": len(subjects), "统一倍率": scale, "前爪目标中心与底边": [123, 241], "各帧测量": report}


def register_animation(root):
    path = root / "assets/animations.json"
    clips = json.loads(path.read_text(encoding="utf-8"))
    if any(frame.startswith('frames/consistent/') for frame in clips.get('scratch', {}).get('frames', [])):
        return
    clips.setdefault("scratch", {"anchor": [123, 241], "loop": False, "transition_ms": 80}).update({
        "anchor": [123, 241],
        "frames": [f"frames/scratch-v2/{index:02}.png" for index in range(16)],
        "durations": [240, 160, 160, 160, 140, 130, 120, 120, 120, 120, 130, 130, 160, 160, 160, 300],
        "blend_ms": 120,
    })
    path.write_text(json.dumps(clips, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="从保留的原分镜复现完整挠耳帧，按需更新动画配置。")
    parser.add_argument("--仅生成帧", action="store_true", help="只生成透明素材，不更新动画配置")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    print(json.dumps(prepare_frames(root), ensure_ascii=False, indent=2))
    if not args.仅生成帧:
        register_animation(root)
        print("已更新挠耳动画配置。")
