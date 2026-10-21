# 安安 · Windows 桌面宠物

以真实布偶猫安安为原型的独立桌宠，保留原 Pets 的形象与动作，增加自主日常行为。原 ChatGPT Pets 安安保持不变。

**已通过本地 16 项测试、Windows 打包与 EXE 启动验证。** 云端构建状态以 Actions 实际结果为准。

- [下载最新版 Windows 成品](https://github.com/WhereamIneeded/anan/releases/latest)
- [查看云端构建](https://github.com/WhereamIneeded/anan/actions)
- [构建和使用说明](docs/构建与使用.md)

## 使用与功能

解压整个成品文件夹，双击 `安安.exe`。成品包含 Python、Qt 和动画，可离线运行。

大小 100～400，默认 220 逻辑像素；悬停注视不跳，单击跳，拖动不误触。随机挠耳、舔爪、哈欠、伸懒腰、环顾、趴睡和仰卧睡；睡觉有进入、保持、翻身和起身过渡。睡眠中点击先起身再跳。支持托盘、安静模式、可选散步、偏好保存与屏幕位置恢复。

## 公司电脑获取最新版

首次执行 `git clone https://github.com/WhereamIneeded/anan.git`，进入仓库；已有克隆先保存本地修改，再执行 `git pull --ff-only`。

安装 Windows x64 Python 3.10 后双击 `构建.cmd`，使用精确依赖运行测试并生成成品。也可直接下载 Releases 最新 ZIP，无需安装开发工具。每份成品的 `版本.json` 记录实际源码提交，独立发布标签与源码、成品保持对应。

## 设计和资料

- [完整执行计划](docs/执行计划.md)、[逐任务实施计划](docs/superpowers/plans/2026-10-22-安安桌面宠物.md)、[实施记录](docs/实施记录.md)。
- [行为设计](docs/行为设计.md)、[素材说明](docs/素材与行为说明.md)、[全部图片索引](docs/图片索引.md)、[原照预览](docs/原始照片预览.md)。
- `src/anan_pet/` 保存程序；`assets/` 保存运行透明帧与逐帧时长；`制作/新增动画/` 保存内置 imagegen 中文提示、四组源分镜及预览。
- `资料/` 保留全部 15 张原照（12 张会话照片）和 301 个历史制作文件。

执行 `python scripts/校验交接资料.py` 核对原始资料。初始 README 和继续提示词保存在 `资料/初始交接README.md`、`资料/初始继续提示词.md`；交接校验清单相应调整路径以保留原快照。

程序不自动读取 Codex 或公司软件的工作状态，不自动开机启动。原工作状态动画提供手动演示。历史交接记录中的“尚未开发”仅指本次实施之前。
