"""从保留的新分镜复现修长体态，整组等比缩放并保持既有播放节奏。"""

import hashlib
import importlib.util
import json
from pathlib import Path

from PIL import Image


def load_helper(filename):
    path = Path(__file__).with_name(filename)
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def prepare_frames(root):
    root = Path(root)
    extractor = load_helper('准备趣味互动素材.py')
    paws = load_helper('准备挠耳连续素材.py')
    reference = root / 'assets/frames/idle/00.png'
    with Image.open(reference) as image:
        box = image.getchannel('A').point(lambda value: 255 if value > 8 else 0).getbbox()
    height = box[3] - box[1]
    config_path = root / 'assets/animations.json'
    config = json.loads(config_path.read_text(encoding='utf-8'))
    groups = (
        ('修长索食分镜.png', 16, 4, [('beg_call', range(8)), ('beg_paw', range(8, 16))]),
        ('修长挠耳分镜.png', 16, 4, [('scratch', range(16))]),
        ('修长日常分镜.png', 6, 3, [('daily', range(6))]),
    )
    report = {'基准': 'assets/frames/idle/00.png', '基准SHA256': hashlib.sha256(reference.read_bytes()).hexdigest(), '组': []}
    for filename, count, columns, definitions in groups:
        source_path = root / '制作/体态统一' / filename
        source = Image.open(source_path).convert('RGBA')
        subjects = extractor.subjects(source, expected=count, columns=columns)
        first = subjects[0]['box']
        scale = height / (first[3] - first[1])
        alpha = source.getchannel('A').load()
        frames, measurements = [], []
        for index, subject in enumerate(subjects):
            bounds = subject['box']
            cell = source.crop(bounds)
            mask = Image.new('L', cell.size)
            pixels = mask.load()
            for point in subject['points']:
                x, y = point % source.width, point // source.width
                pixels[x - bounds[0], y - bounds[1]] = alpha[x, y]
            cell.putalpha(mask)
            cell = cell.resize((round(cell.width * scale), round(cell.height * scale)), Image.Resampling.LANCZOS)
            shape = {'box': cell.getchannel('A').getbbox(), 'points': [i for i, value in enumerate(cell.getchannel('A').tobytes()) if value > 8]}
            paw_x, paw_y = paws.paw_anchor(cell, shape, strip_height=4)
            horizontal_anchor = paw_x
            # 伸懒腰的前爪向前伸，横向按全身中点定位，保留伸展空间与动作幅度。
            if filename == '修长日常分镜.png' and index >= 4:
                horizontal_anchor = (shape['box'][0] + shape['box'][2]) / 2
            offset = (round(123 - horizontal_anchor), round(241 - paw_y))
            if offset[0] <= 0 or offset[1] <= 0 or offset[0] + cell.width >= 256 or offset[1] + cell.height >= 256:
                raise ValueError(f'{filename}第{index + 1}帧超出画布，不能裁切或单帧缩小使用。')
            frame = Image.new('RGBA', (256, 256))
            frame.alpha_composite(cell, offset)
            frames.append(frame)
            measurements.append({'帧': index + 1, '源主体': bounds, '等比倍率': scale, '偏移': offset,
                                 '横向基准': '全身中点' if horizontal_anchor != paw_x else '前爪中心',
                                 '落地前爪': [paw_x + offset[0], paw_y + offset[1]], '成品范围': frame.getchannel('A').getbbox()})
        paths_by_name = {}
        for name, indices in definitions:
            target = root / 'assets/frames/consistent' / name
            target.mkdir(parents=True, exist_ok=True)
            paths = []
            for number, index in enumerate(indices):
                path = target / f'{number:02}.png'
                frames[index].save(path)
                paths.append(path.relative_to(root / 'assets').as_posix())
            paths_by_name[name] = paths
        if 'daily' in paths_by_name:
            for name, indices in (('wash', [0, 1, 0, 1]), ('yawn', [2, 3, 2]), ('stretch', [4, 5, 4])):
                config[name]['frames'] = [paths_by_name['daily'][index] for index in indices]
                config[name]['anchor'] = [123, 241]
        else:
            for name, paths in paths_by_name.items():
                config[name]['frames'] = paths
                config[name]['anchor'] = [123, 241]
        report['组'].append({'源图': filename, '源图SHA256': hashlib.sha256(source_path.read_bytes()).hexdigest(),
                             '帧数': count, '统一倍率': scale, '各帧': measurements})
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (root / '制作/体态统一/帧提取记录.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return report


if __name__ == '__main__':
    root = Path(__file__).resolve().parents[1]
    result = prepare_frames(root)
    print('已提取', sum(group['帧数'] for group in result['组']), '张独立透明帧，既有动作时长保持。')
