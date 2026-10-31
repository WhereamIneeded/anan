"""用临时测试副本验证真实Qt窗口离线切换与默认恢复，导出浅深背景预览。"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage, QPainter
from PySide6.QtWidgets import QApplication

from anan_pet.animation import load_animations, resource_root
from anan_pet.appearance import template_signature
from anan_pet.window import PetWindow


def frame_hashes(window):
    return {key: [hashlib.sha256(bytes(frame.toImage().constBits())).hexdigest() for frame in frames] for key, frames in window.pixmaps.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "build" / "外观恢复预览")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    (ROOT / "build").mkdir(exist_ok=True)
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    font_id = QFontDatabase.addApplicationFont(str(Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts/msyh.ttc"))
    families = QFontDatabase.applicationFontFamilies(font_id)
    font = QFont(families[0] if families else "Microsoft YaHei", 11)
    app.setFont(font)
    assets = resource_root()
    paths = {p for c in load_animations(assets).values() for p in c.frames}
    originals = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths | {assets / "animations.json"}}
    sheet = QImage(1080, 690, QImage.Format.Format_RGB32)
    sheet.fill(QColor("#edf1f4"))
    painter = QPainter(sheet)
    painter.setFont(font)
    with tempfile.TemporaryDirectory(prefix="外观恢复验证-", dir=ROOT / "build") as temporary:
        data = Path(temporary)
        pet_id = "1234567890abcdef1234567890abcdef"
        package = data / "宠物" / pet_id
        package.mkdir(parents=True)
        mapping = {}
        for index, source in enumerate(sorted(paths)):
            name = f"{index:03}.png"
            target = package / name
            shutil.copyfile(source, target)
            # 测试副本统一加蓝色调，方便辨认；这不是照片生成结果。
            image = QImage(str(target))
            tint = QPainter(image)
            tint.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceAtop)
            tint.fillRect(image.rect(), QColor(30, 110, 230, 80))
            tint.end()
            image.save(str(target))
            mapping[source.relative_to(assets).as_posix()] = name
        manifest = {"格式版本": 1, "名称": "蓝调测试副本", "模板校验": template_signature(assets), "帧": mapping}
        (package / "宠物.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        window = PetWindow(data / "偏好.json")
        window.timer.stop()
        window.tray.hide()
        original = frame_hashes(window)
        try:
            for column, label in enumerate(("默认安安", "测试副本（非生成猫）", "恢复默认安安")):
                if column == 1:
                    assert window.activate_custom_pet(pet_id), window.appearance_error
                elif column == 2:
                    assert window.restore_default_pet(), window.appearance_error
                for row, background in enumerate(("#edf1f4", "#263344")):
                    x, y = column * 360, row * 345
                    painter.fillRect(x, y, 360, 345, QColor(background))
                    painter.setPen(QColor("#172638" if row == 0 else "#ffffff"))
                    painter.drawText(x + 15, y + 30, label)
                    image = QImage(window.size(), QImage.Format.Format_ARGB32)
                    image.fill(QColor(0, 0, 0, 0))
                    window.render(image)
                    painter.drawImage(x + 70, y + 65, image)
            restored = frame_hashes(window) == original
            assert restored and package.is_dir()
            assert originals == {p: hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in originals}
            record = {"说明": "真实Qt离屏窗口，临时偏好；蓝调测试副本不是照片生成猫，不调用网络或API。", "独立帧": len(mapping), "动作": len(window.clips), "默认全部帧像素复原": restored, "原素材校验未变": True, "恢复后测试副本保留": package.is_dir(), "预览": "外观恢复浅深对照.png"}
        finally:
            window.close()
            painter.end()
    assert sheet.save(str(args.output / "外观恢复浅深对照.png"))
    (args.output / "外观恢复验证.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(record, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
