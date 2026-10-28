"""导出实际播放器的睡眠唤醒、拖动循环和鼠标转头过程。"""

import argparse
import json
import math
import tempfile
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from 验证动画播放 import prepare, render, rgba_bytes
from PIL import Image
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication

from anan_pet.behavior import BehaviorController
from anan_pet.window import PetWindow


def capture(window, name, output):
    prepare(window)
    config = window.controller.config
    # 预览缩短睡眠保持时间；正式程序的 90～240 秒不变。
    actions = {key: replace(spec, hold_ms=(800, 800)) if spec.loop else spec for key, spec in config.actions.items()}
    window.controller = BehaviorController(window.controller.durations, config=replace(config, actions=actions))
    window.controller.next_action = 1000000
    controller = window.controller
    pictures, states, events = [], [], []
    sleep_started = None
    clicked = False
    duration = {"仰卧醒来再跳": 12000, "趴睡自然醒": 5000, "长拖动": 4000, "转头回正": 3000}[name]
    for now in range(0, duration, 40):
        if now == 0 and name in ("仰卧醒来再跳", "趴睡自然醒"):
            controller.handle("supine" if name == "仰卧醒来再跳" else "sleep", now)
        if name == "长拖动":
            if now == 0:
                controller.handle("drag_start", now)
                controller.set_drag_direction("left", now)
            if now == 1800:
                controller.set_drag_direction("right", now)
            if now == 3400:
                controller.handle("drag_end", now)
        if name == "仰卧醒来再跳" and controller.phase == "loop":
            sleep_started = now if sleep_started is None else sleep_started
            if now - sleep_started >= 320 and not clicked:
                controller.handle("click", now)
                clicked = True
                events.append({"毫秒": now, "事件": "单击，等待翻回起身后跳跃"})
        controller.tick(now)
        direction = (9, 8, 10)[min(now // 800, 2)]
        radians = math.radians(direction * 22.5)
        distance = window.width() if name == "转头回正" and now < 2400 else window.width() * 2
        delta = QPoint(round(math.sin(radians) * distance), round(-math.cos(radians) * distance))
        with patch("anan_pet.window.QCursor.pos", return_value=window.geometry().center() + delta):
            window.update_attention(now)
            window.refresh_frame(now)
        if not states or states[-1]["动画"] != controller.state:
            states.append({"毫秒": now, "动画": controller.state, "阶段": controller.phase})
        _, background, _ = render(window)
        pictures.append(Image.frombytes("RGBA", (256, 256), rgba_bytes(background)))
    pictures[0].save(output / f"{name}.gif", save_all=True, append_images=pictures[1:], duration=40, loop=0, disposal=2)
    sequence = [state["动画"] for state in states]
    if name == "仰卧醒来再跳":
        assert sequence == ["prone_enter", "supine_enter", "supine_sleep", "supine_exit", "prone_exit", "jumping", "idle"]
    elif name == "趴睡自然醒":
        assert sequence == ["prone_enter", "prone_sleep", "prone_exit", "idle"]
    elif name == "长拖动":
        assert sequence == ["running-left", "running-right", "idle"]
    return {"动画顺序": states, "输入事件": events, "预览文件": f"{name}.gif"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="预览输出目录")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    with tempfile.TemporaryDirectory(prefix="anan-behavior-") as directory:
        window = PetWindow(Path(directory) / "偏好.json")
        try:
            window.timer.stop()
            window.tray.hide()
            window.resize(256, 256)
            result = {name: capture(window, name, args.output) for name in ("仰卧醒来再跳", "趴睡自然醒", "长拖动", "转头回正")}
            result["说明"] = "Linux offscreen 平台的实际窗口绘制；睡眠保持时间仅在预览中缩短为 800 毫秒，不修改运行配置和用户偏好。"
            (args.output / "行为验证.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        finally:
            window.timer.stop()
            window.tray.hide()
            window.close()
            app.processEvents()


if __name__ == "__main__":
    main()
