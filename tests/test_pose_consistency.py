"""保证静坐衔接沿用待机体型，保留非静坐动作的自然尺度变化。"""

from PIL import Image
import importlib.util
import json
from pathlib import Path
import shutil
import pytest

from anan_pet.animation import load_animations, resource_root


def visible_box(path):
    with Image.open(path) as image:
        return image.getchannel('A').point(lambda alpha: 255 if alpha > 128 else 0).getbbox()


@pytest.mark.parametrize('name', ('beg_call', 'beg_paw', 'scratch', 'wash', 'yawn', 'eat_enter', 'teaser_ready'))
def test_upright_entry_frames_keep_the_approved_idle_body_scale(name):
    clips = load_animations(resource_root())
    idle = visible_box(clips['idle'].frames[0])
    entry = visible_box(clips[name].frames[0])
    idle_width, idle_height = idle[2] - idle[0], idle[3] - idle[1]
    width, height = entry[2] - entry[0], entry[3] - entry[1]
    assert idle_width * 0.85 <= width <= idle_width * 1.15, f'{name}静坐衔接轮廓尺度不一致：{width}/{idle_width}'
    assert idle_height * 0.90 <= height <= idle_height * 1.08, f'{name}静坐衔接尺度跳变'
    assert abs(entry[3] - idle[3]) <= 3, f'{name}落脚点跳变'


def test_approved_idle_and_look_are_not_replaced():
    clips = load_animations(resource_root())
    for name in ('idle', 'look'):
        assert all(path.parent.name == name for path in clips[name].frames)
    assert len(clips['look'].frames) == 16


def test_preparation_rebuilds_new_frames_without_changing_originals_or_timing(tmp_path):
    root = Path(__file__).resolve().parents[1]
    script = root / 'scripts/准备体态统一素材.py'
    assert script.is_file(), '缺少统一体态的可复现准备脚本'
    spec = importlib.util.spec_from_file_location('consistent_pose_prepare', script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sources = ('修长索食分镜.png', '修长挠耳分镜.png', '修长日常分镜.png')
    for name in sources:
        target = tmp_path / '制作/体态统一' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / '制作/体态统一' / name, target)
    reference = tmp_path / 'assets/frames/idle/00.png'
    reference.parent.mkdir(parents=True)
    reference.write_bytes((root / 'assets/frames/idle/00.png').read_bytes())
    config = tmp_path / 'assets/animations.json'
    config.write_bytes((root / 'assets/animations.json').read_bytes())
    before = json.loads(config.read_text(encoding='utf-8'))
    originals = {name: (tmp_path / '制作/体态统一' / name).read_bytes() for name in sources}
    module.prepare_frames(tmp_path)
    after = json.loads(config.read_text(encoding='utf-8'))
    changed = {'beg_call', 'beg_paw', 'scratch', 'wash', 'yawn', 'stretch'}
    for name, previous in before.items():
        actual = after[name]
        if name not in changed:
            assert actual == previous, f'改变了无关动作：{name}'
        else:
            assert actual['durations'] == previous['durations']
            assert actual['loop'] == previous['loop']
            assert actual.get('blend_ms') == previous.get('blend_ms')
            assert all(path.startswith('frames/consistent/') for path in actual['frames'])
            for path in actual['frames']:
                assert (tmp_path / 'assets' / path).read_bytes() == (root / 'assets' / path).read_bytes()
    assert all((tmp_path / '制作/体态统一' / name).read_bytes() == data for name, data in originals.items())
    assert reference.read_bytes() == (root / 'assets/frames/idle/00.png').read_bytes()


def test_consistent_full_body_frames_are_transparent_complete_and_distinct():
    clips = load_animations(resource_root())
    for name, unique in (('beg_call', 8), ('beg_paw', 8), ('scratch', 16), ('wash', 2), ('yawn', 2), ('stretch', 2)):
        frames = clips[name].frames
        assert all('consistent' in path.parts for path in frames), f'{name}仍使用失配素材'
        pictures = [Image.open(path).convert('RGBA') for path in frames]
        assert len({picture.tobytes() for picture in pictures}) >= unique
        for picture in pictures:
            assert picture.size == (256, 256)
            alpha = picture.getchannel('A')
            box = alpha.getbbox()
            assert alpha.getextrema()[0] == 0
            assert box and min(box[:2]) > 0 and max(box[2:]) < 256
