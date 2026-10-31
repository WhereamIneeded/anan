"""本机偏好与屏幕位置计算，不依赖旧电脑路径。"""

import json
import re


def valid_pet_id(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{32}", value) is not None


def load_settings(path):
    result = {"size": 220, "position": None, "quiet": False, "wander": False, "auto_beg": True, "sound_enabled": False, "active_pet": None, "custom_pet": None}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return result
        size = data.get("size", 220)
        if type(size) in (int, float):
            result["size"] = max(100, min(400, int(size)))
        pos = data.get("position")
        if isinstance(pos, list) and len(pos) == 2 and all(type(n) is int for n in pos):
            result["position"] = pos
        for key in ("quiet", "wander", "sound_enabled"):
            result[key] = data.get(key) is True
        if type(data.get("auto_beg")) is bool:
            result["auto_beg"] = data["auto_beg"]
        for key in ("active_pet", "custom_pet"):
            if valid_pet_id(data.get(key)):
                result[key] = data[key]
    except (OSError, ValueError, TypeError, OverflowError):
        pass
    return result


def save_settings(path, values):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(values, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def visible_position(x, y, width, height, screens):
    def distance(rect):
        sx, sy, sw, sh = rect
        return max(sx - x, 0, x - (sx + sw)) ** 2 + max(sy - y, 0, y - (sy + sh)) ** 2
    sx, sy, sw, sh = min(screens, key=distance)
    return (max(sx, min(x, sx + sw - width)), max(sy, min(y, sy + sh - height)))


def resize_position(x, y, old_w, old_h, new_w, new_h):
    return int(x + (old_w - new_w) / 2), int(y + old_h - new_h)
