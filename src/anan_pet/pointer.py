"""区分单击和拖动，越过阈值后不再恢复为单击。"""


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
