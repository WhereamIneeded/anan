"""验证趣味动作使用完整透明帧，并保持已有素材配置。"""

import importlib.util
import json
import shutil
from pathlib import Path

from PIL import Image, ImageChops

from anan_pet.animation import load_animations, resource_root


NAMES = ("beg_call", "beg_paw", "eat_enter", "eat_loop", "eat_exit", "teaser_ready", "teaser_left", "teaser_right", "teaser_swipe")


def preparer():
    script = Path(__file__).resolve().parents[1] / 'scripts/准备趣味互动素材.py'
    assert script.is_file(), '缺少可复现的新素材准备脚本'
    spec = importlib.util.spec_from_file_location('play_assets_prepare', script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_play_frames_are_complete_and_show_different_poses():
    clips = load_animations(resource_root())
    assert set(NAMES) <= clips.keys(), "趣味动作尚未注册"
    for name in NAMES:
        clip = clips[name]
        assert len(clip.frames) >= 4
        images = [Image.open(path).convert("RGBA") for path in clip.frames]
        for im in images:
            assert im.size == (256, 256)
            alpha = im.getchannel("A")
            box = alpha.getbbox()
            assert alpha.getextrema()[0] == 0 and box
            assert 0 < box[0] < box[2] < 256
            assert 0 < box[1] < box[3] < 256
        assert len({im.tobytes() for im in images}) >= 4
    assert ImageChops.difference(Image.open(clips['eat_enter'].frames[0]), Image.open(clips['eat_loop'].frames[0])).getbbox()
    assert clips['eat_loop'].loop
    assert all(clips[name].stabilization is None for name in NAMES)


def test_prepare_preserves_previous_animations_and_originals(tmp_path):
    root = Path(__file__).resolve().parents[1]
    module = preparer()
    (tmp_path / 'assets').mkdir()
    before = {name: info for name, info in json.loads((root / 'assets/animations.json').read_text(encoding='utf-8')).items() if name not in NAMES}
    (tmp_path / 'assets/animations.json').write_text(json.dumps(before), encoding='utf-8')
    target = tmp_path / '制作/趣味互动'
    target.mkdir(parents=True)
    originals = {}
    for name in ('索食分镜.png', '进食分镜.png', '逗猫分镜.png'):
        shutil.copy2(root / '制作/趣味互动' / name, target / name)
        originals[name] = (target / name).read_bytes()
    module.prepare_frames(tmp_path)
    after = json.loads((tmp_path / 'assets/animations.json').read_text(encoding='utf-8'))
    assert {key: after[key] for key in before} == before
    assert set(NAMES) <= after.keys()
    assert all((target / name).read_bytes() == data for name, data in originals.items())


def test_optional_meow_has_valid_short_pcm_wave_and_source():
    import wave
    root = resource_root()
    path = root / 'audio/meow.wav'
    assert path.is_file(), "尚未提供有来源的可选猫叫"
    with wave.open(str(path), 'rb') as recording:
        assert recording.getcomptype() == 'NONE'
        assert 0.1 < recording.getnframes() / recording.getframerate() < 4
    assert (root / 'audio/来源说明.md').is_file()


def test_bowl_and_food_layers_fit_original_cat_canvas():
    root = resource_root()
    for name in ('bowl_back', 'bowl_front', 'snack-1', 'snack-2', 'snack-3', 'freeze_dried-1', 'freeze_dried-2', 'freeze_dried-3'):
        path = root / 'props' / (name + '.png')
        assert path.is_file(), f'缺少可组合的道具层：{name}'
        with Image.open(path) as image:
            assert image.size == (256, 256)
            box = image.getchannel('A').getbbox()
            assert box and box[0] > 0 and box[2] < 256 and box[3] < 256
    assert (root / 'props/teaser.png').is_file()


def test_audio_preparation_preserves_original_and_reproduces_runtime_file(tmp_path):
    root = Path(__file__).resolve().parents[1]
    original = root / '制作/趣味互动/音频原始/cat_mewfood.wav'
    copied = tmp_path / '制作/趣味互动/音频原始/cat_mewfood.wav'
    copied.parent.mkdir(parents=True)
    shutil.copy2(original, copied)
    result = preparer().prepare_audio(tmp_path)
    assert copied.read_bytes() == original.read_bytes()
    assert result.read_bytes() == (root / 'assets/audio/meow.wav').read_bytes()
