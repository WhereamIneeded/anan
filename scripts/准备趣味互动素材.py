"""提取新分镜的完整透明主体，统一倍率与落脚点，保留源图和旧动作。"""

import argparse
import array
import hashlib
import importlib.util
import json
import wave
from pathlib import Path

from PIL import Image, ImageDraw


def subjects(image):
    width, height = image.size
    remaining = bytearray(value > 8 for value in image.getchannel('A').tobytes())
    found = []
    for start in range(width * height):
        if not remaining[start]:
            continue
        remaining[start] = 0
        pending, points = [start], []
        while pending:
            index = pending.pop()
            points.append(index)
            x, y = index % width, index // width
            for ny in range(max(0, y - 1), min(height, y + 2)):
                for nx in range(max(0, x - 1), min(width, x + 2)):
                    other = ny * width + nx
                    if remaining[other]:
                        remaining[other] = 0
                        pending.append(other)
        # 分镜透明区有独立的零星低透明噪点，不把它们当作猫咪。
        if len(points) < 1000:
            continue
        xs, ys = [i % width for i in points], [i // width for i in points]
        found.append({'points': points, 'box': (min(xs), min(ys), max(xs) + 1, max(ys) + 1), 'center': (sum(xs) / len(xs), sum(ys) / len(ys))})
    if len(found) != 16:
        raise ValueError(f'分镜应有16只完整猫咪，实际为{len(found)}，请检查源图。')
    found.sort(key=lambda item: item['center'][1])
    return [item for row in range(4) for item in sorted(found[row * 4:row * 4 + 4], key=lambda item: item['center'][0])]


def prepare_frames(root):
    root = Path(root)
    helper_path = Path(__file__).with_name('准备挠耳连续素材.py')
    spec = importlib.util.spec_from_file_location('scratch_frame_helper', helper_path)
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    groups = {
        '索食分镜.png': [('beg_call', range(8), 175, False), ('beg_paw', range(8, 16), 175, False)],
        '进食分镜.png': [('eat_enter', range(8), 150, False), ('eat_loop', range(8, 12), 230, True), ('eat_exit', range(12, 16), 900, False)],
        '逗猫分镜.png': [('teaser_ready', range(4), 450, True), ('teaser_left', range(4, 8), 250, True), ('teaser_right', range(8, 12), 250, True), ('teaser_swipe', range(12, 16), 250, False)],
    }
    config_path = root / 'assets/animations.json'
    config = json.loads(config_path.read_text(encoding='utf-8'))
    report = []
    for filename, definitions in groups.items():
        source_path = root / '制作/趣味互动' / filename
        source = Image.open(source_path).convert('RGBA')
        cats = subjects(source)
        scale = 173 / (cats[0]['box'][3] - cats[0]['box'][1])
        frames = []
        for index, cat in enumerate(cats):
            box = cat['box']
            cell = source.crop(box)
            # 仅保留本只完整主体；不重画猫、不改变姿势，也不覆盖源图。
            mask = Image.new('L', cell.size)
            pixels = mask.load()
            alpha = source.getchannel('A').load()
            for point in cat['points']:
                x, y = point % source.width, point // source.width
                pixels[x - box[0], y - box[1]] = alpha[x, y]
            cell.putalpha(mask)
            cell = cell.resize((round(cell.width * scale), round(cell.height * scale)), Image.Resampling.LANCZOS)
            shape = {'box': cell.getchannel('A').getbbox(), 'points': [i for i, value in enumerate(cell.getchannel('A').tobytes()) if value > 8]}
            paw_x, paw_y = helper.paw_anchor(cell, shape, strip_height=4)
            offset = (round(123 - paw_x), round(241 - paw_y))
            frame = Image.new('RGBA', (256, 256))
            frame.alpha_composite(cell, offset)
            bounds = frame.getchannel('A').getbbox()
            if not bounds or min(bounds[:2]) <= 0 or max(bounds[2:]) >= 256:
                raise ValueError(f'{filename}第{index + 1}帧超出画布，不能裁切使用。')
            frames.append(frame)
            report.append({'源图': filename, '源图SHA256': hashlib.sha256(source_path.read_bytes()).hexdigest(), '序号': index, '主体范围': box, '统一倍率': scale, '落脚偏移': offset, '成品范围': bounds})
        for name, indices, duration, loop in definitions:
            paths = []
            target = root / 'assets/frames' / name
            target.mkdir(parents=True, exist_ok=True)
            for number, index in enumerate(indices):
                path = target / f'{number:02d}.png'
                frames[index].save(path)
                paths.append(path.relative_to(root / 'assets').as_posix())
            config[name] = {'frames': paths, 'durations': [duration] * len(paths), 'blend_ms': 100, 'loop': loop, 'anchor': [123, 241], 'transition_ms': 120}
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (root / '制作/趣味互动/帧提取记录.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return report


def prepare_audio(root):
    root = Path(root)
    source = root / '制作/趣味互动/音频原始/cat_mewfood.wav'
    with wave.open(str(source), 'rb') as recording:
        rate, channels, width = recording.getframerate(), recording.getnchannels(), recording.getsampwidth()
        if width != 2:
            raise ValueError('原始猫叫应为16位PCM音频。')
        values = array.array('h', recording.readframes(recording.getnframes()))
    mono = [sum(values[i:i + channels]) / channels for i in range(0, len(values), channels)]
    fade = max(1, int(rate * 0.015))
    output = array.array('h', (round(value * 0.35 * min(1, i / fade, (len(mono) - 1 - i) / fade)) for i, value in enumerate(mono)))
    target = root / 'assets/audio/meow.wav'
    target.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(target), 'wb') as recording:
        recording.setparams((1, 2, rate, len(output), 'NONE', 'not compressed'))
        recording.writeframes(output.tobytes())
    return target


def prepare_props(root):
    target = Path(root) / 'assets/props'
    target.mkdir(parents=True, exist_ok=True)
    # 简单道具采用确定性绘图；猫咪全部来自独立生成的新分镜。
    back = Image.new('RGBA', (256, 256))
    draw = ImageDraw.Draw(back)
    draw.ellipse((91, 226, 155, 242), fill='#a7bbc8', outline='#637f93', width=1)
    draw.ellipse((96, 229, 150, 239), fill='#506c80')
    back.save(target / 'bowl_back.png')
    front = Image.new('RGBA', (256, 256))
    draw = ImageDraw.Draw(front)
    draw.polygon([(92, 239), (154, 239), (148, 251), (99, 251)], fill='#c8e2ed')
    draw.arc((92, 232, 154, 246), 0, 180, fill='#f5fdff', width=3)
    draw.line((99, 250, 148, 250), fill='#728e9d', width=1)
    front.save(target / 'bowl_front.png')
    positions = [(104, 234), (113, 231), (121, 235), (130, 232), (139, 235), (115, 236), (133, 236), (125, 230), (144, 232)]
    for food, color in [('snack', '#b77845'), ('freeze_dried', '#f1c993')]:
        for level, count in [(1, 2), (2, 5), (3, 9)]:
            image = Image.new('RGBA', (256, 256))
            draw = ImageDraw.Draw(image)
            for x, y in positions[:count]:
                draw.rounded_rectangle((x - 2, y - 2, x + 2, y + 2), 1, fill=color, outline='#906b47')
            image.save(target / f'{food}-{level}.png')
    toy = Image.new('RGBA', (80, 100))
    draw = ImageDraw.Draw(toy)
    draw.line((70, 93, 50, 39), fill='#87634c', width=4)
    draw.arc((24, 17, 60, 62), 185, 300, fill='#aa8c70', width=2)
    draw.ellipse((22, 17, 37, 37), fill='#d7b6e8', outline='#a380b4')
    draw.ellipse((14, 12, 25, 34), fill='#a9dce9', outline='#78adbd')
    draw.line((22, 19, 28, 41), fill='#e6f6fc', width=1)
    draw.line((29, 22, 29, 42), fill='#f6eafa', width=1)
    draw.ellipse((25, 35, 33, 43), fill='#f3d68c', outline='#b19757')
    toy.save(target / 'teaser.png')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='从新分镜提取趣味互动透明帧。')
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    arguments = parser.parse_args()
    print(f'已提取{len(prepare_frames(arguments.root))}张新姿势，保留历史素材与原动作配置。')
    prepare_props(arguments.root)
    prepare_audio(arguments.root)
