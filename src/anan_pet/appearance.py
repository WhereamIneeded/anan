"""只读外观整包加载；默认安安与本机自定义帧彼此隔离。"""

import hashlib
import json
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath

from PySide6.QtGui import QImage, QImageReader, QPixmap

from .animation import GROUND_ANCHOR, load_animations
from .rendering import align_pixmap, remove_green_spill, stabilize_idle, stabilize_look
from .settings import valid_pet_id


class AppearanceError(ValueError):
    """外观包不完整或不符合本机格式。"""


@dataclass
class Appearance:
    name: str
    pet_id: str | None
    clips: dict
    pixmaps: dict


def template_signature(default_root):
    data = json.loads((default_root / "animations.json").read_text(encoding="utf-8"))
    normalized = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _inside(root, relative):
    if not isinstance(relative, str) or not relative or "\\" in relative or ":" in relative:
        raise AppearanceError("外观帧路径无效")
    path = PurePosixPath(relative)
    if path.is_absolute() or any(part in (".", "..") for part in relative.split("/")):
        raise AppearanceError("外观帧路径越界")
    target = (root / relative).resolve()
    if not target.is_relative_to(root) or target.suffix.lower() != ".png":
        raise AppearanceError("外观帧必须为目录内的 PNG 文件")
    return target


def _custom(default_root, custom_root, clips):
    if not valid_pet_id(custom_root.name) or custom_root.is_symlink():
        raise AppearanceError("自定义宠物标识无效")
    root = custom_root.resolve()
    manifest = root / "宠物.json"
    if not manifest.resolve().is_relative_to(root) or manifest.stat().st_size > 512 * 1024:
        raise AppearanceError("外观清单过大或越界")
    data = json.loads(manifest.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or type(data.get("格式版本")) is not int or data["格式版本"] != 1:
        raise AppearanceError("外观格式版本无效")
    name = data.get("名称")
    if not isinstance(name, str) or not name.strip() or len(name) > 32 or any(not c.isprintable() for c in name):
        raise AppearanceError("宠物名称须为不超过32字的非空单行文字")
    if data.get("模板校验") != template_signature(default_root):
        raise AppearanceError("外观动作模板与当前程序不匹配")
    slots = {p.relative_to(default_root).as_posix() for c in clips.values() for p in c.frames}
    mapping = data.get("帧")
    if not isinstance(mapping, dict) or set(mapping) != slots:
        raise AppearanceError("外观必须完整覆盖当前全部动作帧")
    paths = {key: _inside(root, value) for key, value in mapping.items()}
    if len(set(paths.values())) != len(paths):
        raise AppearanceError("不同动作帧须使用独立图片文件")
    cache = {}
    for path in paths.values():
        if path.stat().st_size > 2 * 1024 * 1024:
            raise AppearanceError("外观图片超过2MiB")
        reader = QImageReader(str(path))
        size = reader.size()
        if bytes(reader.format()).lower() != b"png" or (size.width(), size.height()) != (256, 256):
            raise AppearanceError("外观图片必须是256×256的PNG")
        image = reader.read()
        if image.isNull() or not image.hasAlphaChannel():
            raise AppearanceError("外观图片缺少透明通道或无法解码")
        image = image.convertToFormat(QImage.Format.Format_RGBA8888)
        alpha = bytes(image.constBits())[3::4]
        if min(alpha) != 0 or max(alpha) < 128 or sum(value >= 32 for value in alpha) < 64:
            raise AppearanceError("外观图片须同时包含可见主体与透明背景")
        cache[path] = QPixmap.fromImage(image)
    result = {key: replace(c, frames=[paths[p.relative_to(default_root).as_posix()] for p in c.frames], anchor=GROUND_ANCHOR, stabilization=None) for key, c in clips.items()}
    return Appearance(name.strip(), custom_root.name, result, {key: [cache[p] for p in c.frames] for key, c in result.items()})


def load_appearance(default_root, custom_root=None):
    clips = load_animations(default_root)
    if custom_root is not None:
        try:
            return _custom(default_root, Path(custom_root), clips)
        except AppearanceError:
            raise
        except (OSError, ValueError, TypeError, RuntimeError, RecursionError) as error:
            raise AppearanceError("自定义外观无法读取或已损坏") from error
    paths = {p for clip in clips.values() for p in clip.frames}
    cache = {p: remove_green_spill(QPixmap(str(p))) for p in paths}
    pixmaps = {key: [align_pixmap(cache[p], clip.anchor) for p in clip.frames] for key, clip in clips.items()}
    for key, clip in clips.items():
        policy = clip.stabilization
        if policy and policy.eyes:
            pixmaps[key] = stabilize_idle(pixmaps[key], policy.eyes, policy.radius)
        elif policy and policy.head_bottom is not None:
            pixmaps[key] = stabilize_look(pixmaps[key], pixmaps["idle"][0], policy.head_bottom, policy.body_top)
    return Appearance("安安", None, clips, pixmaps)
