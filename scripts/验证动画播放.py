"""以实际 Qt 绘制路径导出动画预览与测量，不读取或修改用户偏好。"""

import argparse
import json
import os
import platform
import random
import statistics
import sys
import tempfile
import time
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PIL import Image
from PySide6.QtCore import QEventLoop, QTimer, qVersion
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from anan_pet.behavior import BehaviorController
from anan_pet.window import PetWindow


def distribution(values):
    """保留小数以便比较，性能结果只作观测，不作为易波动的通过阈值。"""
    ordered = sorted(values)

    def percentile(fraction):
        position = (len(ordered) - 1) * fraction
        lower = int(position)
        upper = min(lower + 1, len(ordered) - 1)
        return round(ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower), 4)

    if not ordered:
        return {"样本数": 0}
    return {"样本数": len(ordered), "P50毫秒": percentile(0.5), "P95毫秒": percentile(0.95), "最大毫秒": round(ordered[-1], 4)}


def rgba_bytes(image):
    image = image.convertToFormat(QImage.Format.Format_RGBA8888)
    raw = bytes(image.constBits())
    stride, row_size = image.bytesPerLine(), image.width() * 4
    return b"".join(raw[y * stride:y * stride + row_size] for y in range(image.height()))


def render(window):
    """QWidget.render 会调用窗口自身的 paintEvent，包含实际缩放和抗锯齿。"""
    transparent = QImage(window.size(), QImage.Format.Format_ARGB32_Premultiplied)
    transparent.fill(QColor(0, 0, 0, 0))
    started = time.perf_counter_ns()
    window.render(transparent)
    elapsed = (time.perf_counter_ns() - started) / 1_000_000
    background = QImage(window.size(), QImage.Format.Format_RGB32)
    background.fill(QColor("#dceef8"))
    painter = QPainter(background)
    painter.drawImage(0, 0, transparent)
    painter.end()
    return transparent, background, elapsed


def prepare(window):
    window.controller = BehaviorController({key: clip.total_ms for key, clip in window.clips.items()}, random.Random(0))
    window.controller.next_action = 1_000_000
    window.hovering = False
    window.frame = window.pixmaps["idle"][0]
    window.frame_signature = None
    window.visual_key = "idle"
    window.visual_index = 0
    window.transition_source = None
    window.transition_duration = 0
    window.transition_body_top = None


def capture(window, action, output):
    prepare(window)
    if action != "idle":
        window.controller.handle(action, 0)
    clip = window.clips[action]
    # GIF 以 10 毫秒计时，20 毫秒采样能够保持预览时长准确。
    step = 20
    total = clip.total_ms + (0 if action == "idle" else 400)
    times = list(range(0, total, step))
    pictures, refresh_ms, paint_ms, states = [], [], [], []
    previous_body = previous_background = None
    maximum = [0, 0, 0, 0]
    background_maximum = [0, 0, 0]
    changed_pairs = 0
    unique_images = set()
    for now in times:
        window.controller.tick(now)
        states.append(window.controller.state)
        started = time.perf_counter_ns()
        window.refresh_frame(now)
        refresh_ms.append((time.perf_counter_ns() - started) / 1_000_000)
        transparent, background, elapsed = render(window)
        paint_ms.append(elapsed)
        body = rgba_bytes(transparent.copy(0, 128, window.width(), window.height() - 128))
        background_body = rgba_bytes(background.copy(0, 128, window.width(), window.height() - 128))
        if previous_body is not None:
            differences = [max((abs(a - b) for a, b in zip(previous_body[channel::4], body[channel::4])), default=0) for channel in range(4)]
            maximum = [max(old, new) for old, new in zip(maximum, differences)]
            background_differences = [max((abs(a - b) for a, b in zip(previous_background[channel::4], background_body[channel::4])), default=0) for channel in range(3)]
            background_maximum = [max(old, new) for old, new in zip(background_maximum, background_differences)]
            changed_pairs += any(differences)
        previous_body = body
        previous_background = background_body
        rgba = rgba_bytes(background)
        unique_images.add(rgba)
        # Pillow 只接收 Qt 已绘制好的像素并编码 GIF，不参与合成、缩放或插帧。
        pictures.append(Image.frombytes("RGBA", (window.width(), window.height()), rgba))
    destination = output / ("待机眨眼.gif" if action == "idle" else "挠耳朵.gif")
    pictures[0].save(destination, save_all=True, append_images=pictures[1:], duration=step, loop=0, disposal=2, optimize=False)
    return {
        "预览文件": destination.name,
        "清单帧数": len(clip.frames),
        "清单逐帧毫秒": clip.durations,
        "清单总毫秒": clip.total_ms,
        "清单过渡毫秒": getattr(clip, "blend_ms", 0),
        "采样间隔毫秒": step,
        "采样帧数": len(times),
        "不同画面数": len(unique_images),
        "状态顺序": list(dict.fromkeys(states)),
        "refresh_frame耗时": distribution(refresh_ms),
        "实际paintEvent渲染耗时": distribution(paint_ms),
        "身体区域": {"矩形": [0, 128, window.width(), window.height() - 128], "相邻画面最大RGB差": maximum[:3], "相邻画面最大透明度差": maximum[3], "浅蓝背景相邻画面最大RGB差": background_maximum, "有变化的相邻画面对数": changed_pairs},
    }


def sample_timer(window, seconds):
    prepare(window)
    window.origin_time = time.monotonic()
    window.previous_advance_ms = 0
    timestamps = []
    observe = lambda: timestamps.append(time.perf_counter_ns())
    window.timer.timeout.connect(observe)
    loop = QEventLoop()
    QTimer.singleShot(round(seconds * 1000), loop.quit)
    window.timer.start()
    loop.exec()
    window.timer.stop()
    window.timer.timeout.disconnect(observe)
    intervals = [(right - left) / 1_000_000 for left, right in zip(timestamps, timestamps[1:])]
    return {"说明": "无界面平台的实际 QTimer 采样，只作观测，不能替代桌面显示器体验验收。", "设定间隔毫秒": window.timer.interval(), "请求采样秒数": seconds, "实际间隔": distribution(intervals), "间隔平均毫秒": round(statistics.mean(intervals), 4) if intervals else None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="预览和测量结果的输出目录")
    parser.add_argument("--timer-seconds", type=float, default=0, help="可选：额外采样实际定时器的秒数")
    args = parser.parse_args()
    if args.timer_seconds < 0:
        parser.error("定时器采样时间不能小于零")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    with tempfile.TemporaryDirectory(prefix="anan-playback-") as temporary:
        window = PetWindow(Path(temporary) / "偏好.json")
        try:
            window.timer.stop()
            window.tray.hide()
            app.processEvents()
            window.hide()
            window.resize(256, 256)
            results = {"环境": {"Python": platform.python_version(), "Qt": qVersion(), "平台": app.platformName(), "画布像素": [256, 256]}, "说明": "使用临时偏好、确定性时间轴、实际 Qt 绘制路径。身体测量使用透明截图，GIF 使用浅蓝背景。耗时包含首帧，不设置性能通过阈值。", "待机": capture(window, "idle", output), "挠耳": capture(window, "scratch", output)}
            if args.timer_seconds:
                results["实际定时器"] = sample_timer(window, args.timer_seconds)
            (output / "播放测量.json").write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(json.dumps(results, ensure_ascii=False, indent=2))
        finally:
            window.timer.stop()
            window.tray.hide()
            window.close()
            app.processEvents()


if __name__ == "__main__":
    main()
