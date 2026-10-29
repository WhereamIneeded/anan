"""检查运行素材是否来自已去绿边的最终图集。"""

from pathlib import Path

from PIL import Image


STATES = (("idle", 6), ("running-right", 8), ("running-left", 8), ("waving", 4), ("jumping", 5), ("failed", 8), ("waiting", 6), ("running", 6), ("review", 6))


def test_runtime_frames_use_final_atlas_instead_of_green_screen_intermediates():
    root = Path(__file__).resolve().parents[1]
    with Image.open(root / "资料/历史制作档案/成品与预览/安安精灵图.png") as atlas:
        for row, (name, count) in enumerate(STATES):
            for index in range(count):
                expected = Image.new("RGBA", (256, 256))
                expected.alpha_composite(atlas.crop((index * 192, row * 208, (index + 1) * 192, (row + 1) * 208)), (32, 40))
                with Image.open(root / f"assets/frames/{name}/{index:02}.png") as actual:
                    assert actual.convert("RGBA").tobytes() == expected.tobytes(), f"{name}/{index:02} 使用了未清理的中间素材"


def test_regenerating_existing_frames_preserves_new_animations(tmp_path):
    import json
    import runpy
    import shutil

    root = Path(__file__).resolve().parents[1]
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    shutil.copy2(root / "scripts/准备既有素材.py", scripts)
    atlas = tmp_path / "资料/历史制作档案/成品与预览/安安精灵图.png"
    atlas.parent.mkdir(parents=True)
    shutil.copy2(root / "资料/历史制作档案/成品与预览/安安精灵图.png", atlas)
    assets = tmp_path / "assets"
    assets.mkdir()
    config = assets / "animations.json"
    config.write_bytes((root / "assets/animations.json").read_bytes())
    before = json.loads(config.read_text(encoding="utf-8"))
    runpy.run_path(str(scripts / "准备既有素材.py"), run_name="__main__")
    assert json.loads(config.read_text(encoding="utf-8")) == before, "重新提取旧动作不应删除睡眠、新版挠耳或改变播放时长"


def test_regenerating_daily_frames_preserves_pose_and_stage_configuration(tmp_path):
    import json
    import shutil
    import subprocess
    import sys

    root = Path(__file__).resolve().parents[1]
    for name in ("scripts/准备新增素材.py", "scripts/准备挠耳连续素材.py", "assets/animations.json", "assets/behaviors.json", "制作/动画优化/挠耳连续分镜.png", *(f"制作/新增动画/{name}-源图.png" for name in ("scratch", "prone", "supine", "daily"))):
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / name, target)
    config = tmp_path / "assets/animations.json"
    before = json.loads(config.read_text(encoding="utf-8"))
    # 新版引用独立素材目录，历史准备脚本的预览也需要完整运行输入。
    for name in {frame for clip in before.values() for frame in clip['frames'] if frame.startswith('frames/consistent/')}:
        target = tmp_path / 'assets' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / 'assets' / name, target)
    subprocess.run([sys.executable, str(tmp_path / "scripts/准备新增素材.py")], cwd=tmp_path, check=True, capture_output=True)
    assert json.loads(config.read_text(encoding="utf-8")) == before, "重建日常和挠耳帧不能丢失锚点、循环或稳定区域"
    assert (tmp_path / "assets/behaviors.json").read_bytes() == (root / "assets/behaviors.json").read_bytes()
