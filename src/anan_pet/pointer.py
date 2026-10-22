"""区分单击和拖动，越过阈值后不再恢复为单击。"""

import math


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
