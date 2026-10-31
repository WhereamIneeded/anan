"""外观整包校验及默认像素回归。"""

import hashlib
import json
import os
import shutil

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QImage, QColor, QPixmap
from PySide6.QtWidgets import QApplication

try:
    from anan_pet import appearance
except ImportError:
    appearance = None
from anan_pet.animation import resource_root, load_animations
from anan_pet.rendering import align_pixmap, remove_green_spill, stabilize_idle, stabilize_look
from anan_pet.settings import load_settings

PET_ID = "1234567890abcdef1234567890abcdef"


def test_appearance_loader_available():
    assert appearance is not None, "尚未实现隔离的外观加载入口"


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


def make_package(root):
    """逐个复制真实帧，保留不同槽位的独立文件。"""
    root.mkdir(parents=True)
    assets = resource_root()
    paths = {p for c in load_animations(assets).values() for p in c.frames}
    mapping = {}
    for index, path in enumerate(sorted(paths)):
        target = f"帧/{index:03}.png"
        (root / target).parent.mkdir(exist_ok=True)
        shutil.copyfile(path, root / target)
        mapping[path.relative_to(assets).as_posix()] = target
    manifest = {"格式版本": 1, "名称": "测试副本", "模板校验": appearance.template_signature(assets), "帧": mapping}
    write_manifest(root, manifest)
    return manifest


def write_manifest(root, manifest):
    (root / "宠物.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")


def pixels(pixmap):
    image = pixmap.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
    return hashlib.sha256(bytes(image.constBits())).hexdigest()


def test_default_pixels_equal_original_pipeline(app):
    assets = resource_root()
    clips = load_animations(assets)
    cache = {p: remove_green_spill(QPixmap(str(p))) for c in clips.values() for p in c.frames}
    expected = {k: [align_pixmap(cache[p], c.anchor) for p in c.frames] for k, c in clips.items()}
    for key, clip in clips.items():
        policy = clip.stabilization
        if policy and policy.eyes:
            expected[key] = stabilize_idle(expected[key], policy.eyes, policy.radius)
        elif policy and policy.head_bottom is not None:
            expected[key] = stabilize_look(expected[key], expected["idle"][0], policy.head_bottom, policy.body_top)
    result = appearance.load_appearance(assets)
    assert result.name == "安安" and result.pet_id is None
    assert {k: list(map(pixels, v)) for k, v in result.pixmaps.items()} == {k: list(map(pixels, v)) for k, v in expected.items()}


def test_complete_package_keeps_timing_and_green(app, tmp_path):
    root = tmp_path / PET_ID
    manifest = make_package(root)
    assert len(manifest["帧"]) == 155
    target = root / next(iter(manifest["帧"].values()))
    image = QImage(256, 256, QImage.Format.Format_ARGB32)
    image.fill(QColor(0, 0, 0, 0))
    for x in range(120, 128):
        for y in range(120, 128):
            image.setPixelColor(x, y, QColor(0, 255, 0, 255))
    image.save(str(target))
    result = appearance.load_appearance(resource_root(), root)
    assert len(result.clips) == 29 and result.pet_id == PET_ID
    for key, clip in result.clips.items():
        original = load_animations(resource_root())[key]
        assert clip.durations == original.durations and clip.loop == original.loop
        assert clip.stabilization is None
        for path, pixmap in zip(clip.frames, result.pixmaps[key]):
            if path == target:
                assert pixmap.toImage().pixelColor(120, 120).green() == 255


@pytest.mark.parametrize("problem", ["missing", "extra", "duplicate", "template", "escape", "absolute", "ads", "bad", "size", "transparent", "opaque", "manifest", "version", "name", "type", "huge_image"])
def test_invalid_package_rejected_whole(app, tmp_path, problem):
    root = tmp_path / PET_ID
    manifest = make_package(root)
    key = next(iter(manifest["帧"]))
    target = root / manifest["帧"][key]
    if problem == "missing": del manifest["帧"][key]
    elif problem == "extra": manifest["帧"]["多余.png"] = "多余.png"
    elif problem == "duplicate": manifest["帧"][key] = list(manifest["帧"].values())[1]
    elif problem == "template": manifest["模板校验"] = "错误"
    elif problem == "escape": manifest["帧"][key] = "../越界.png"
    elif problem == "absolute": manifest["帧"][key] = target.as_posix()
    elif problem == "ads": manifest["帧"][key] = "帧/000.png:隐藏流"
    elif problem == "version": manifest["格式版本"] = True
    elif problem == "name": manifest["名称"] = "测试\n冒名"
    elif problem == "type": manifest["帧"] = []
    elif problem == "bad": target.write_bytes(b"broken")
    elif problem in ("size", "transparent", "opaque", "huge_image"):
        size = 512 if problem == "size" else 4096 if problem == "huge_image" else 256
        image = QImage(size, size, QImage.Format.Format_ARGB32)
        image.fill(QColor(0, 0, 0, 0 if problem == "transparent" else 255))
        image.save(str(target))
    write_manifest(root, manifest)
    if problem == "manifest": (root / "宠物.json").write_bytes(b" " * (512 * 1024 + 1))
    with pytest.raises(appearance.AppearanceError):
        appearance.load_appearance(resource_root(), root)


@pytest.mark.parametrize("value", [None, "../猫", "A" * 32, "a" * 31, 123, False])
def test_preferences_reject_invalid_ids(tmp_path, value):
    path = tmp_path / "偏好.json"
    path.write_text(json.dumps({"size": 300, "active_pet": value, "custom_pet": value}), encoding="utf-8")
    loaded = load_settings(path)
    assert loaded["active_pet"] is None and loaded["custom_pet"] is None
    assert loaded["size"] == 300


def test_preferences_keep_ids_and_old_defaults(tmp_path):
    path = tmp_path / "偏好.json"
    assert load_settings(path)["active_pet"] is None
    path.write_text(json.dumps({"active_pet": PET_ID, "custom_pet": PET_ID}), encoding="utf-8")
    assert load_settings(path)["active_pet"] == PET_ID


@pytest.mark.parametrize("alpha", [128, 1])
def test_no_transparent_background_or_invisible_body_rejected(app, tmp_path, alpha):
    root = tmp_path / PET_ID
    manifest = make_package(root)
    image = QImage(256, 256, QImage.Format.Format_ARGB32)
    image.fill(QColor(120, 120, 120, alpha))
    if alpha == 1:
        image.setPixelColor(0, 0, QColor(0, 0, 0, 0))
    image.save(str(root / next(iter(manifest["帧"].values()))))
    with pytest.raises(appearance.AppearanceError):
        appearance.load_appearance(resource_root(), root)


def test_template_signature_ignores_json_layout(tmp_path):
    original = json.loads((resource_root() / "animations.json").read_text(encoding="utf-8"))
    (tmp_path / "animations.json").write_text(json.dumps(original, indent=4, sort_keys=True), encoding="utf-8")
    assert appearance.template_signature(tmp_path) == appearance.template_signature(resource_root())


def test_oversized_frame_rejected_before_decode(app, tmp_path):
    root = tmp_path / PET_ID
    manifest = make_package(root)
    target = root / next(iter(manifest["帧"].values()))
    with target.open("ab") as stream:
        stream.write(b" " * (2 * 1024 * 1024))
    with pytest.raises(appearance.AppearanceError):
        appearance.load_appearance(resource_root(), root)


def test_frame_symlink_cannot_escape_package(app, tmp_path):
    root = tmp_path / PET_ID
    manifest = make_package(root)
    target = root / next(iter(manifest["帧"].values()))
    outside = tmp_path / "目录外.png"
    target.replace(outside)
    try:
        target.symlink_to(outside)
    except OSError:
        pytest.skip("当前Windows账号不能创建符号链接")
    with pytest.raises(appearance.AppearanceError):
        appearance.load_appearance(resource_root(), root)


def test_name_cannot_contain_unicode_line_control(app, tmp_path):
    root = tmp_path / PET_ID
    manifest = make_package(root)
    manifest["名称"] = "第一行\u0085第二行"
    write_manifest(root, manifest)
    with pytest.raises(appearance.AppearanceError):
        appearance.load_appearance(resource_root(), root)
