"""区分单击与拖动，并根据当前鼠标位置判断短暂关注。"""

import math


class AttentionTracker:
    def __init__(self):
        self.position = None
        self.last_movement_ms = 0
        self.active = False

    def update(self, position, center, width, now_ms, eligible=True):
        moved = position != self.position
        self.position = position
        if not eligible:
            self.active = False
            return False
        distance_squared = sum((value - origin) ** 2 for value, origin in zip(position, center))
        if self.active and (distance_squared > (width * 1.5) ** 2 or now_ms - self.last_movement_ms >= 3000):
            self.active = False
        if moved:
            self.last_movement_ms = now_ms
            if distance_squared <= (width * 1.2) ** 2:
                self.active = True
        return self.active


def look_direction(dx, dy, previous, dead_zone=12):
    if dx * dx + dy * dy < dead_zone * dead_zone:
        return previous
    angle = math.degrees(math.atan2(dx, -dy)) % 360
    distance = (angle - previous * 22.5 + 180) % 360 - 180
    if abs(distance) <= 15.25:
        return previous
    return round(angle / 22.5) % 16


class Gesture:
    def __init__(self, threshold=10):
        self.threshold = threshold
        self.origin = None
        self.dragging = False

    def press(self, x, y):
        self.origin = (x, y)
        self.dragging = False

    def move(self, x, y):
        if self.origin is not None:
            self.dragging |= abs(x - self.origin[0]) + abs(y - self.origin[1]) >= self.threshold
        return self.dragging

    def release(self):
        clicked = self.origin is not None and not self.dragging
        self.origin = None
        self.dragging = False
        return clicked
