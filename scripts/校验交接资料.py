"""使用标准库核对交接快照、照片来源和历史制作档案。"""

import hashlib
import json
import sys
from pathlib import Path


def 文件摘要(路径):
    摘要 = hashlib.sha256()
    with 路径.open("rb") as 文件:
        for 数据块 in iter(lambda: 文件.read(1024 * 1024), b""):
            摘要.update(数据块)
    return 摘要.hexdigest()


def 主函数():
    根目录 = Path(__file__).resolve().parents[1]
    清单路径 = 根目录 / "资料/文件校验.json"
    if not 清单路径.is_file():
        print("缺少资料/文件校验.json，请确认已完整克隆仓库。")
        return 1
    清单 = json.loads(清单路径.read_text(encoding="utf-8"))
    错误 = []
    for 记录 in 清单["文件"]:
        路径 = 根目录 / 记录["路径"]
        if not 路径.is_file():
            错误.append(f"缺少文件：{记录['路径']}")
        elif 路径.stat().st_size != 记录["字节数"] or 文件摘要(路径) != 记录["SHA256"]:
            错误.append(f"文件发生变化：{记录['路径']}")

    来源 = json.loads((根目录 / "资料/来源清单.json").read_text(encoding="utf-8"))
    照片 = 来源["原始照片"]
    会话照片 = [记录 for 记录 in 照片 if 记录["会话明确提供"]]
    if len(照片) != 15 or len(会话照片) != 12:
        错误.append("照片数量不符：应包含 15 张原照，其中 12 张为会话明确提供。")
    if len(来源["历史档案文件"]) != 301:
        错误.append("历史制作档案应包含 301 个文件。")
    if len(来源["本地源文件对照"]) != 276 or len(来源["本地成品对照"]) != 25:
        错误.append("历史源文件或成品对照数量不符。")
    for 记录 in 照片 + 来源["历史档案文件"]:
        路径 = 根目录 / 记录["仓库路径"]
        if not 路径.is_file() or 文件摘要(路径) != 记录["SHA256"]:
            错误.append(f"来源核对失败：{记录['仓库路径']}")

    图集 = 根目录 / "资料/历史制作档案/成品与预览/安安精灵图.png"
    if not 图集.is_file() or 文件摘要(图集) != "d0002453c7fe3e930d9e117d0a5d462455d7b293dfbd38111ced06714b0aca1e":
        错误.append("最终精灵图与已批准版本不一致。")

    if 错误:
        print("校验未通过：")
        for 内容 in 错误:
            print(f"- {内容}")
        return 1
    总量 = sum(记录["字节数"] for 记录 in 清单["文件"])
    print(f"校验通过：{len(清单['文件'])} 个快照文件，共 {总量:,} 字节。")
    print("原照 15 张，会话照片 12 张；历史档案 301 个文件完整。")
    print("历史源文件 276 个、成品 25 个均已匹配，最终精灵图哈希一致。")
    print("此结果验证资料完整性，不代表尚未开发的桌面程序已经构建或运行。")
    return 0


if __name__ == "__main__":
    sys.exit(主函数())
