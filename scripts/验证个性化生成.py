"""在普通终端逐张验证个性化猫咪，密钥仅留在当前进程内存。"""

import argparse
import getpass
import os
from pathlib import Path
import sys
import warnings


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from anan_pet.image_service import ImageService, ServiceError
from anan_pet.personalization_probe import (
    ProbeError, accept_base, generate_next, prepare_task, preview_task, retry_pose,
)


def main(argv=None):
    parser = argparse.ArgumentParser(description="逐张验证七个个性化猫咪代表姿势；不是完整动画导入工具。")
    commands = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (("prepare", "离线准备照片和七个动作模板"),
                            ("generate", "最多请求生成一张图片，可能产生费用"),
                            ("accept", "明确确认已成功生成的待机基准"),
                            ("retry", "明确授权指定姿势重做；此命令本身不联网"),
                            ("preview", "离线导出深浅背景与姿势顺序预览")):
        command = commands.add_parser(name, help=help_text, description=help_text)
        command.add_argument("--output", type=Path, default=ROOT / "build/个性化验证", help="任务目录，默认为项目 build/个性化验证")
        if name == "prepare":
            command.add_argument("--photo", type=Path, required=True, help="用户自有猫咪的单张照片")
            command.add_argument("--subject", default="", help="多猫照片中的目标猫咪说明，最多300字；默认空")
        if name == "retry":
            command.add_argument("--pose", required=True, help="完整姿势标识，例如 look[4]")
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            state = prepare_task(args.photo, args.output, ROOT / "assets", subject=args.subject)
        elif args.command == "accept":
            state = accept_base(args.output)
        elif args.command == "retry":
            state = retry_pose(args.output, args.pose)
        elif args.command == "preview":
            for path in preview_task(args.output):
                print(f"预览已导出：{path}")
            return 0
        else:
            key = os.environ.get("OPENAI_API_KEY", "").strip()
            if not key:
                if not sys.stdin.isatty():
                    raise ProbeError("非交互终端缺少 OPENAI_API_KEY 密钥，未发送请求。")
                try:
                    with warnings.catch_warnings():
                        warnings.simplefilter("error", getpass.GetPassWarning)
                        key = getpass.getpass("请输入 OpenAI 密钥（隐藏输入，仅保存在本进程）：").strip()
                except getpass.GetPassWarning:
                    raise ProbeError("终端不支持隐藏输入，已停止；请在支持隐藏输入的普通终端运行。") from None
            state = generate_next(args.output, ImageService(key))
        print(f"请求次数：{state['请求次数']}/10；待机基准已确认：{'是' if state['基准已确认'] else '否'}")
        for row in state["姿势列表"]:
            print(f"{row['姿势']}：{row['状态']}")
        return 0 if not any(row["状态"] in {"失败", "不合格", "结果未确认"} for row in state["姿势列表"]) else 1
    except (ProbeError, ServiceError) as exc:
        print(f"操作停止：{exc}", file=sys.stderr)
        return 1
    except OSError:
        print("操作停止：本地文件无法读写，请检查目录权限与磁盘空间。", file=sys.stderr)
        return 1
    except (EOFError, KeyboardInterrupt):
        print("操作已中止；若请求已发出，请检查任务状态及账户用量。", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
