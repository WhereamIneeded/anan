"""独立验证七个猫咪代表姿势，不接入桌宠运行程序。"""

from contextlib import contextmanager
import hashlib
import io
import json
import os
from pathlib import Path
import re
import time
import warnings

from PIL import Image, ImageDraw, ImageFont, ImageOps, PngImagePlugin

from .image_service import MODEL, ServiceError, safe_usage


MAX_PHOTO_BYTES = 20 * 1024 * 1024
MAX_PHOTO_PIXELS = 24_000_000
REQUEST_LIMIT = 10
PROMPT_VERSION = 1
POSES = (
    ("idle[0]", "idle-0", "frames/idle/00.png", "正面自然坐姿待机"),
    ("look[4]", "look-4", "frames/look/04.png", "保持坐姿，头部与视线朝向模板方向"),
    ("look[12]", "look-12", "frames/look/12.png", "保持坐姿，头部与视线朝向模板另一方向"),
    ("waving[1]", "waving-1", "frames/waving/01.png", "抬起一只前爪招呼，采用模板第一姿势"),
    ("waving[2]", "waving-2", "frames/waving/02.png", "继续抬爪招呼，采用模板第二姿势"),
    ("eat_loop[1]", "eat_loop-1", "frames/eat_loop/01.png", "低头进食的身体姿势，不画食盆与道具"),
    ("supine_sleep[0]", "supine_sleep-0", "frames/supine/03.png", "仰卧熟睡，四爪自然蜷起，不能画成坐姿旋转"),
)
STATES = {"待生成", "请求中", "结果未确认", "失败", "不合格", "已完成"}


class ProbeError(Exception):
    """可以直接展示的本地操作错误。"""


def _path(root, relative):
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise ProbeError("任务路径无效或越界。")
    target = (root / relative).resolve()
    if not target.is_relative_to(root) or target == root:
        raise ProbeError("任务路径无效或越界。")
    return target


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _save(root, state):
    temporary = _path(root, "任务.json.tmp")
    with temporary.open("w", encoding="utf-8") as file:
        json.dump(state, file, ensure_ascii=False, indent=2, allow_nan=False)
        file.write("\n")
        file.flush()
        os.fsync(file.fileno())
    os.replace(temporary, _path(root, "任务.json"))


@contextmanager
def _locked(root):
    """操作期间持有系统文件锁，进程崩溃后由系统释放。"""
    if not root.is_dir():
        raise ProbeError("任务目录不存在，请先准备任务。")
    with _path(root, ".操作锁").open("a+b") as file:
        if file.tell() == 0:
            file.write(b"0")
            file.flush()
        file.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise ProbeError("此任务正在被另一个进程操作，请稍后再试。") from None
        try:
            yield
        finally:
            file.seek(0)
            if os.name == "nt":
                msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(file, fcntl.LOCK_UN)


def _load(root):
    try:
        path = _path(root, "任务.json")
        if path.stat().st_size > 1024 * 1024:
            raise ProbeError("任务文件过大。")
        state = json.loads(path.read_text(encoding="utf-8"))
        if state.get("模型") != MODEL or state.get("提示版本") != PROMPT_VERSION:
            raise ProbeError("任务模型或提示版本已变化，请保留旧任务并另建任务。")
        rows = state["姿势列表"]
        if (state["格式版本"] != 1 or type(state["请求次数"]) is not int
                or not 0 <= state["请求次数"] <= REQUEST_LIMIT
                or type(state["基准已确认"]) is not bool or len(rows) != len(POSES)):
            raise ValueError
        seen = []
        for row, (name, slug, _, _) in zip(rows, POSES):
            if row["姿势"] != name or row["状态"] not in STATES or row["模板"] != f"模板/{slug}.png":
                raise ValueError
            _path(root, row["模板"])
            for attempt in row["尝试"]:
                number = attempt["序号"]
                if type(number) is not int or not 1 <= number <= REQUEST_LIMIT:
                    raise ValueError
                seen.append(number)
                prefix = f"尝试/{number:02d}-{slug}"
                for key, filename in (("原始图", "原始.png"), ("规范图", "规范.png"), ("提示文件", "提示.txt")):
                    if attempt[key] != f"{prefix}/{filename}":
                        raise ValueError
                    _path(root, attempt[key])
            if row["状态"] != "待生成" and not row["尝试"]:
                raise ValueError
        if sorted(seen) != list(range(1, state["请求次数"] + 1)):
            raise ValueError
        expected = {"原照.bin", "参考.png"} | {f"模板/{item[1]}.png" for item in POSES}
        if set(state["输入校验"]) != expected:
            raise ValueError
        for relative, digest in state["输入校验"].items():
            if _sha(_path(root, relative).read_bytes()) != digest:
                raise ProbeError("任务输入校验失败；照片或模板已变更，请另建任务。")
        if state["基准已确认"]:
            base = rows[0]
            if base["状态"] != "已完成" or _sha(_path(root, base["尝试"][-1]["原始图"]).read_bytes()) != state["基准校验"]:
                raise ProbeError("已确认基准校验失败，请另建任务。")
        recovered = False
        for row in rows:
            if row["状态"] == "请求中":
                row["状态"] = "结果未确认"
                row["尝试"][-1]["状态"] = "结果未确认"
                row["尝试"][-1]["说明"] = "上次请求未正常结束，请先核对账户用量；仅明确重做才允许再次请求。"
                recovered = True
        if recovered:
            _save(root, state)
        return state
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        raise ProbeError("任务文件无效、缺失或输入校验失败。") from None


def _clean_photo(raw):
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as source:
                if source.width * source.height > MAX_PHOTO_PIXELS:
                    raise ProbeError("照片像素过大，请先缩小照片。")
                if getattr(source, "n_frames", 1) != 1:
                    raise ProbeError("请选择单张静态照片。")
                oriented = ImageOps.exif_transpose(source)
                oriented.load()
                clean = Image.new("RGB", oriented.size, "white")
                if "A" in oriented.getbands():
                    clean.paste(oriented.convert("RGB"), mask=oriented.getchannel("A"))
                else:
                    clean.paste(oriented.convert("RGB"))
                clean.thumbnail((2048, 2048), Image.Resampling.LANCZOS)
                stream = io.BytesIO()
                clean.save(stream, "PNG")
                return stream.getvalue()
    except (OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ProbeError("照片无法解码或像素过大，请提供有效的静态照片。") from None


def prepare_task(photo, output, assets):
    """复制原照与动作模板，生成零请求的离线任务。"""
    photo, root, assets = Path(photo).resolve(), Path(output).resolve(), Path(assets).resolve()
    if root.is_relative_to(assets) or assets.is_relative_to(root) or photo.is_relative_to(root):
        raise ProbeError("输出目录不能覆盖照片或安安素材目录。")
    if root.exists() and (not root.is_dir() or any(root.iterdir())):
        raise ProbeError("输出目录非空，拒绝覆盖；请使用新的空目录。")
    try:
        if photo.stat().st_size > MAX_PHOTO_BYTES:
            raise ProbeError("照片文件过大，请限制在 20 MiB 内。")
        raw = photo.read_bytes()
        clean = _clean_photo(raw)
        inputs = {"原照.bin": raw, "参考.png": clean}
        for _, slug, relative, _ in POSES:
            inputs[f"模板/{slug}.png"] = _path(assets, relative).read_bytes()
    except OSError:
        raise ProbeError("照片或安安动作模板无法读取。") from None
    root.mkdir(parents=True, exist_ok=True)
    with _locked(root):
        if any(item.name != ".操作锁" for item in root.iterdir()):
            raise ProbeError("输出目录非空，拒绝覆盖。")
        for relative, data in inputs.items():
            target = _path(root, relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        state = {"格式版本": 1, "模型": MODEL, "提示版本": PROMPT_VERSION,
                 "说明": "七个代表姿势验证，不是完整动画或已导入角色。",
                 "请求次数": 0, "基准已确认": False, "基准校验": None,
                 "输入校验": {name: _sha(data) for name, data in inputs.items()},
                 "姿势列表": [{"姿势": name, "模板": f"模板/{slug}.png", "状态": "待生成", "尝试": []}
                              for name, slug, _, _ in POSES]}
        _save(root, state)
    return state


def _prompt(index, confirmed):
    identity = ("第一张是用户自有猫咪照片，唯一决定角色身份、花色、毛长、眼色、体态比例。"
                "第二张是安安动作模板，仅参考姿势、机位、画面占比和脚底落点；"
                "不能继承安安的长毛、蓝眼或花色，不能把安安直接换色冒充新猫。")
    if confirmed:
        identity += "第三张是用户已确认的个性化待机基准，保持与它一致的猫咪身份、画风和体态比例。"
    return (identity + f"本次只生成一张代表姿势：{POSES[index][3]}。"
            "绘制完整猫咪，身体不可裁切，四周留白；保持固定镜头尺度和正交视角。"
            "参考模板在1024×1024画布上的相对位置与落地基线，正常坐姿脚底约在画布94%高度，"
            "仰卧姿势按模板保持地面关系，不按包围盒等高放大。透明背景，边缘自然，"
            "不要地板、投影、文字、装饰与额外角色；不要绿幕。")


def _normalize(png):
    try:
        with Image.open(io.BytesIO(png)) as image:
            if image.format != "PNG" or image.size != (1024, 1024) or "A" not in image.getbands():
                raise ProbeError("生成图必须是含真实透明通道的 1024×1024 PNG。")
            image.load()
            alpha = image.getchannel("A")
            low, high = alpha.getextrema()
            histogram = alpha.histogram()
            if low != 0 or high < 128 or sum(histogram[32:]) < 1024:
                raise ProbeError("生成图缺少透明背景或可见主体。")
            result = image.convert("RGBA").resize((256, 256), Image.Resampling.LANCZOS)
            stream = io.BytesIO()
            result.save(stream, "PNG")
            return stream.getvalue()
    except (OSError, ValueError, Image.DecompressionBombError):
        raise ProbeError("生成图无法解码或格式不合格。") from None


def generate_next(output, service):
    """每次最多发送一次请求；失败和未知结果必须显式重做。"""
    root = Path(output).resolve()
    with _locked(root):
        state = _load(root)
        rows = state["姿势列表"]
        blocked = {"结果未确认", "失败", "不合格"}
        if any(row["状态"] in blocked for row in rows):
            raise ProbeError("存在失败、不合格或结果未确认的姿势，请先检查结果并明确重做。")
        pending = next((i for i, row in enumerate(rows) if row["状态"] == "待生成"), None)
        if pending is None:
            return state
        if pending != 0 and not state["基准已确认"]:
            raise ProbeError("请先查看并明确确认待机基准，再生成其他姿势。")
        if state["请求次数"] >= REQUEST_LIMIT:
            raise ProbeError("本任务已达到 10 次请求上限，不能继续请求。")
        row = rows[pending]
        prompt = _prompt(pending, state["基准已确认"])
        images = [_path(root, "参考.png").read_bytes(), _path(root, row["模板"]).read_bytes()]
        if state["基准已确认"]:
            images.append(_path(root, rows[0]["尝试"][-1]["原始图"]).read_bytes())
        number = state["请求次数"] + 1
        prefix = f"尝试/{number:02d}-{POSES[pending][1]}"
        folder = _path(root, prefix)
        if folder.exists():
            raise ProbeError("本次尝试目录已存在，拒绝覆盖历史结果。")
        folder.mkdir(parents=True)
        attempt = {"序号": number, "状态": "请求中", "原始图": f"{prefix}/原始.png",
                   "规范图": f"{prefix}/规范.png", "提示文件": f"{prefix}/提示.txt",
                   "耗时秒": None, "用量": {}, "请求标识": None}
        _path(root, attempt["提示文件"]).write_text(prompt, encoding="utf-8")
        row["尝试"].append(attempt)
        row["状态"] = "请求中"
        state["请求次数"] = number
        _save(root, state)
        started = time.monotonic()
        try:
            result = service.edit(prompt, images)
        except ServiceError as exc:
            attempt["状态"] = "结果未确认" if exc.uncertain else "失败"
            attempt["说明"] = "请求未取得可验证结果，请先检查账户用量；明确重做会产生新请求。"
        else:
            _path(root, attempt["原始图"]).write_bytes(result.png)
            attempt["用量"] = safe_usage(result.usage)
            request_id = result.request_id
            attempt["请求标识"] = request_id if isinstance(request_id, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", request_id) else None
            try:
                normalized = _normalize(result.png)
            except ProbeError as exc:
                attempt["状态"] = "不合格"
                attempt["说明"] = str(exc)
            else:
                _path(root, attempt["规范图"]).write_bytes(normalized)
                attempt["状态"] = "已完成"
        attempt["耗时秒"] = round(time.monotonic() - started, 3)
        row["状态"] = attempt["状态"]
        _save(root, state)
        return state


def accept_base(output):
    root = Path(output).resolve()
    with _locked(root):
        state = _load(root)
        base = state["姿势列表"][0]
        if base["状态"] != "已完成":
            raise ProbeError("待机基准尚未成功生成，不能确认。")
        raw = _path(root, base["尝试"][-1]["原始图"]).read_bytes()
        _normalize(raw)
        state["基准校验"] = _sha(raw)
        state["基准已确认"] = True
        _save(root, state)
        return state


def retry_pose(output, pose):
    """只授权指定姿势下一次重做，不在这里发起请求。"""
    root = Path(output).resolve()
    with _locked(root):
        state = _load(root)
        if state["请求次数"] >= REQUEST_LIMIT:
            raise ProbeError("本任务已达到 10 次请求上限。")
        rows = state["姿势列表"]
        row = next((item for item in rows if item["姿势"] == pose), None)
        if row is None:
            raise ProbeError("姿势名称无效，请使用任务中的完整姿势标识。")
        if row["状态"] == "待生成":
            raise ProbeError("该姿势已经等待生成，无需重做授权。")
        if row is rows[0]:
            if any(item["尝试"] for item in rows[1:]):
                raise ProbeError("后续姿势已有付费尝试，拒绝重做基准；请保留本任务并另建任务。")
            state["基准已确认"] = False
            state["基准校验"] = None
        row["状态"] = "待生成"
        _save(root, state)
        return state


def _font():
    font_root = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    for name in ("msyh.ttc", "simhei.ttf", "simsun.ttc"):
        path = font_root / name
        if path.is_file():
            return ImageFont.truetype(str(path), 17)
    raise ProbeError("未找到系统中文字体，无法导出带中文标签的预览。")


def preview_task(output, offline=False):
    """导出深浅背景和姿势顺序示意，不将代表姿势称作完整动画。"""
    root = Path(output).resolve()
    with _locked(root):
        state = _load(root)
        font = _font()
        title = "离线合成测试 · " if offline else ""
        title += "七个代表姿势 · 非完整动画"
        completed = sum(row["状态"] == "已完成" for row in state["姿势列表"])
        title += f" · 已完成 {completed}/7"
        sheet = Image.new("RGB", (560, 50 + 300 * 7), "#eeeeee")
        ImageDraw.Draw(sheet).text((8, 12), title, fill="#172333", font=font)
        sequence = []
        for index, row in enumerate(state["姿势列表"]):
            cells = []
            for color, ink in (("#f6f5f0", "#192333"), ("#263344", "#f6f5f0")):
                cell = Image.new("RGB", (280, 300), color)
                draw = ImageDraw.Draw(cell)
                draw.text((10, 6), f"{row['姿势']} · {row['状态']}", fill=ink, font=font)
                if row["状态"] == "已完成":
                    with Image.open(_path(root, row["尝试"][-1]["规范图"])) as frame:
                        rgba = frame.convert("RGBA")
                        cell.paste(rgba, (12, 34), rgba)
                else:
                    draw.text((30, 140), "尚无合格结果", fill=ink, font=font)
                cells.append(cell)
            for column, cell in enumerate(cells):
                sheet.paste(cell, (column * 280, 50 + index * 300))
            frame = Image.new("RGB", (560, 350), "#eeeeee")
            ImageDraw.Draw(frame).text((8, 12), title, fill="#172333", font=font)
            for column, cell in enumerate(cells):
                frame.paste(cell, (column * 280, 50))
            sequence.append(frame)
        preview = _path(root, "预览")
        preview.mkdir(exist_ok=True)
        paths = [_path(root, "预览/深浅对照.png"), _path(root, "预览/姿势顺序.gif")]
        metadata = PngImagePlugin.PngInfo()
        metadata.add_text("Description", title)
        sheet.save(paths[0], pnginfo=metadata)
        sequence[0].save(paths[1], save_all=True, append_images=sequence[1:], duration=1000, loop=0,
                         comment=title.encode("utf-8"))
        return paths
