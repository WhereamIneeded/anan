"""用离线合成图片验证代表姿势的费用门禁与恢复行为。"""

import importlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import warnings

import pytest
from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/验证个性化生成.py"


def probe():
    return importlib.import_module("anan_pet.personalization_probe")


def image_bytes(size=(1024, 1024), mode="RGBA", opaque=False):
    image = Image.new(mode, size, (0, 0, 0, 255) if opaque else (0, 0, 0, 0))
    if not opaque:
        ImageDraw.Draw(image).ellipse((size[0] // 4, size[1] // 4, size[0] * 3 // 4, size[1] * 3 // 4), fill=(160, 90, 40, 255))
    stream = io.BytesIO()
    image.save(stream, "PNG")
    return stream.getvalue()


class FakeService:
    def __init__(self, png=None, error=None):
        self.calls = []
        self.png = png if png is not None else image_bytes()
        self.error = error

    def edit(self, prompt, images):
        self.calls.append((prompt, images))
        if self.error:
            raise self.error
        service = importlib.import_module("anan_pet.image_service")
        return service.ImageResult(self.png, {"total_tokens": 10}, "offline_synthetic")


@pytest.fixture
def prepared(tmp_path):
    photo = tmp_path / "用户照片.png"
    photo.write_bytes(image_bytes((60, 80)))
    output = tmp_path / "结果"
    state = probe().prepare_task(photo, output, ROOT / "assets")
    return photo, output, state


def read_state(output):
    return json.loads((output / "任务.json").read_text(encoding="utf-8"))


def write_state(output, state):
    (output / "任务.json").write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")


def test_prepare_creates_seven_slots_without_modifying_sources(prepared):
    photo, output, state = prepared
    assert state["请求次数"] == 0 and state["基准已确认"] is False
    assert [row["姿势"] for row in state["姿势列表"]] == ["idle[0]", "look[4]", "look[12]", "waving[1]", "waving[2]", "eat_loop[1]", "supine_sleep[0]"]
    assert all(row["状态"] == "待生成" for row in state["姿势列表"])
    assert photo.read_bytes() == (output / "原照.bin").read_bytes()
    assert (output / "参考.png").is_file()
    assert len(list((output / "模板").glob("*.png"))) == 7
    assert "密钥" not in (output / "任务.json").read_text(encoding="utf-8")


def test_prepare_applies_exif_and_removes_metadata(tmp_path):
    photo = tmp_path / "横置.jpg"
    image = Image.new("RGB", (30, 50), "orange")
    exif = image.getexif()
    exif[274] = 6
    exif[315] = "不应进入联网参考"
    image.save(photo, exif=exif)
    before = photo.read_bytes()
    probe().prepare_task(photo, tmp_path / "结果", ROOT / "assets")
    with Image.open(tmp_path / "结果/参考.png") as cleaned:
        assert cleaned.size == (50, 30) and not cleaned.getexif() and not cleaned.info
    assert photo.read_bytes() == before


def test_prepare_refuses_invalid_photo_nonempty_output_and_oversize(tmp_path, monkeypatch):
    photo = tmp_path / "照片.png"
    photo.write_bytes("不是照片".encode())
    with pytest.raises(probe().ProbeError, match="照片"):
        probe().prepare_task(photo, tmp_path / "结果", ROOT / "assets")
    photo.write_bytes(image_bytes((20, 20)))
    output = tmp_path / "非空"
    output.mkdir()
    (output / "已有.txt").write_text("保留", encoding="utf-8")
    with pytest.raises(probe().ProbeError, match="非空"):
        probe().prepare_task(photo, output, ROOT / "assets")
    monkeypatch.setattr(probe(), "MAX_PHOTO_PIXELS", 10)
    with pytest.raises(probe().ProbeError, match="像素"):
        probe().prepare_task(photo, tmp_path / "大图", ROOT / "assets")


def test_base_confirmation_gates_remaining_calls_and_finished_task_never_repeats(prepared):
    _, output, _ = prepared
    fake = FakeService()
    first = probe().generate_next(output, fake)
    assert first["请求次数"] == 1 and first["姿势列表"][0]["状态"] == "已完成"
    with pytest.raises(probe().ProbeError, match="确认"):
        probe().generate_next(output, fake)
    assert len(fake.calls) == 1
    probe().accept_base(output)
    for _ in range(6):
        last = probe().generate_next(output, fake)
    assert last["请求次数"] == 7 and len(fake.calls) == 7
    assert probe().generate_next(output, fake)["请求次数"] == 7
    assert len(fake.calls) == 7
    assert len(fake.calls[0][1]) == 2 and len(fake.calls[1][1]) == 3
    prompt = fake.calls[1][0]
    assert all(word in prompt for word in ("第一张", "第二张", "第三张", "花色", "蓝眼", "透明"))
    normalized = output / last["姿势列表"][1]["尝试"][-1]["规范图"]
    with Image.open(normalized) as image:
        assert image.size == (256, 256)
        assert image.getchannel("A").point(lambda alpha: 255 if alpha >= 128 else 0).getbbox()[0] == 64


def test_timeout_is_counted_and_requires_explicit_retry(prepared):
    _, output, _ = prepared
    service = importlib.import_module("anan_pet.image_service")
    fake = FakeService(error=service.ServiceError("请求超时，结果未确认", uncertain=True))
    state = probe().generate_next(output, fake)
    assert state["请求次数"] == 1 and state["姿势列表"][0]["状态"] == "结果未确认"
    with pytest.raises(probe().ProbeError, match="重做"):
        probe().generate_next(output, fake)
    assert len(fake.calls) == 1
    probe().retry_pose(output, "idle[0]")
    assert probe().generate_next(output, FakeService())["请求次数"] == 2


def test_crash_after_persisting_request_does_not_resend(prepared):
    _, output, _ = prepared

    class Crash:
        def edit(self, *_):
            state = read_state(output)
            assert state["请求次数"] == 1
            assert state["姿势列表"][0]["状态"] == "请求中"
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        probe().generate_next(output, Crash())
    fake = FakeService()
    with pytest.raises(probe().ProbeError, match="重做"):
        probe().generate_next(output, fake)
    assert read_state(output)["姿势列表"][0]["状态"] == "结果未确认"
    assert not fake.calls


def test_explicit_redo_hard_limit_preserves_all_paid_attempts(prepared):
    _, output, _ = prepared
    fake = FakeService()
    probe().generate_next(output, fake)
    probe().accept_base(output)
    for _ in range(6):
        probe().generate_next(output, fake)
    with pytest.raises(probe().ProbeError, match="基准"):
        probe().retry_pose(output, "idle[0]")
    for _ in range(3):
        probe().retry_pose(output, "look[4]")
        probe().generate_next(output, fake)
    with pytest.raises(probe().ProbeError, match="10"):
        probe().retry_pose(output, "look[4]")
    assert len(fake.calls) == 10
    state = read_state(output)
    assert len(state["姿势列表"][1]["尝试"]) == 4
    assert all((output / attempt["原始图"]).is_file() for attempt in state["姿势列表"][1]["尝试"])


@pytest.mark.parametrize("payload", ["坏图".encode(), image_bytes((512, 512)), image_bytes(opaque=True),
                                    image_bytes(mode="RGB"), image_bytes().replace(b"PNG", b"JPG", 1)])
def test_invalid_generated_images_are_kept_but_never_accepted(prepared, payload):
    _, output, _ = prepared
    state = probe().generate_next(output, FakeService(payload))
    row = state["姿势列表"][0]
    assert state["请求次数"] == 1 and row["状态"] == "不合格"
    assert (output / row["尝试"][-1]["原始图"]).read_bytes() == payload
    with pytest.raises(probe().ProbeError, match="基准"):
        probe().accept_base(output)


def test_fully_transparent_image_is_rejected(prepared):
    _, output, _ = prepared
    stream = io.BytesIO()
    Image.new("RGBA", (1024, 1024)).save(stream, "PNG")
    assert probe().generate_next(output, FakeService(stream.getvalue()))["姿势列表"][0]["状态"] == "不合格"


@pytest.mark.parametrize("path", ["参考.png", "原照.bin", "模板/idle-0.png"])
def test_modified_input_hash_prevents_network(prepared, path):
    _, output, _ = prepared
    (output / path).write_bytes("已更改".encode())
    fake = FakeService()
    with pytest.raises(probe().ProbeError, match="校验"):
        probe().generate_next(output, fake)
    assert not fake.calls


def test_path_traversal_prevents_network(prepared):
    _, output, state = prepared
    state["姿势列表"][0]["模板"] = "../外部.png"
    write_state(output, state)
    fake = FakeService()
    with pytest.raises(probe().ProbeError, match="路径|任务"):
        probe().generate_next(output, fake)
    assert not fake.calls


def test_service_key_never_enters_task_files_even_when_remote_fields_echo_it(prepared):
    import base64

    _, output, _ = prepared
    service_module = importlib.import_module("anan_pet.image_service")
    secret = "sk-offline-never-save-this-key"

    class Response(io.BytesIO):
        status = 200
        headers = {"x-request-id": "req_" + secret}

    payload = json.dumps({"data": [{"b64_json": base64.b64encode(image_bytes()).decode()}],
                          "usage": {"total_tokens": 3, "secret": secret}}).encode()
    service = service_module.ImageService(secret, lambda *_: Response(payload))
    assert probe().generate_next(output, service)["请求次数"] == 1
    assert all(secret.encode() not in path.read_bytes() for path in output.rglob("*") if path.is_file())


def test_base_can_be_redone_before_other_attempts_and_old_result_is_retained(prepared):
    _, output, _ = prepared
    original = probe().generate_next(output, FakeService())
    old_path = output / original["姿势列表"][0]["尝试"][0]["原始图"]
    old_bytes = old_path.read_bytes()
    probe().accept_base(output)
    pending = probe().retry_pose(output, "idle[0]")
    assert pending["基准已确认"] is False
    assert old_path.read_bytes() == old_bytes
    updated = probe().generate_next(output, FakeService())
    assert len(updated["姿势列表"][0]["尝试"]) == 2
    with pytest.raises(probe().ProbeError, match="确认"):
        probe().generate_next(output, FakeService())


@pytest.mark.parametrize("field,bad_value", [("模型", "unexpected-model"), ("提示版本", 999)])
def test_model_or_prompt_version_change_prevents_resuming(prepared, field, bad_value):
    _, output, state = prepared
    state[field] = bad_value
    write_state(output, state)
    fake = FakeService()
    with pytest.raises(probe().ProbeError, match="版本"):
        probe().generate_next(output, fake)
    assert not fake.calls


def test_cli_refuses_plaintext_fallback_when_hidden_key_input_is_unavailable(prepared, monkeypatch, capsys):
    import getpass
    import importlib.util

    _, output, _ = prepared
    spec = importlib.util.spec_from_file_location("probe_cli_hidden_input", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    fake = FakeService()
    monkeypatch.setattr(module, "ImageService", lambda _: fake)

    def unavailable(*args):
        warnings.warn("离线模拟无法关闭回显", getpass.GetPassWarning)
        return "不应回退到此处"

    monkeypatch.setattr(getpass, "getpass", unavailable)
    assert module.main(["generate", "--output", str(output)]) == 1
    assert not fake.calls
    assert "隐藏输入" in capsys.readouterr().err


def test_preview_exports_partial_and_complete_offline_contact_sheets_and_gif(prepared):
    _, output, _ = prepared
    paths = probe().preview_task(output, offline=True)
    assert {p.name for p in paths} == {"深浅对照.png", "姿势顺序.gif"}
    assert read_state(output)["请求次数"] == 0
    fake = FakeService()
    probe().generate_next(output, fake)
    probe().accept_base(output)
    for _ in range(6):
        probe().generate_next(output, fake)
    paths = probe().preview_task(output, offline=True)
    with Image.open(paths[1]) as animation:
        assert animation.n_frames == 7
    with Image.open(paths[0]) as sheet:
        assert sheet.width >= 512 and sheet.height > 256
        assert "离线合成测试" in sheet.info["Description"]


def test_process_lock_prevents_duplicate_charge_and_competing_mutations(prepared):
    _, output, _ = prepared
    code = '''import io, sys
from pathlib import Path
from anan_pet.personalization_probe import generate_next
from anan_pet.image_service import ImageResult
from PIL import Image
class HoldingService:
    def edit(self, prompt, images):
        print("请求已开始", flush=True)
        sys.stdin.readline()
        stream = io.BytesIO()
        Image.new("RGBA", (1024, 1024)).save(stream, "PNG")
        return ImageResult(stream.getvalue(), {}, "offline_synthetic")
generate_next(Path(sys.argv[1]), HoldingService())
'''
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"), PYTHONUTF8="1")
    process = subprocess.Popen([sys.executable, "-c", code, str(output)], cwd=ROOT, env=env,
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, encoding="utf-8")
    try:
        assert process.stdout.readline().strip() == "请求已开始"
        fake = FakeService()
        for operation in (lambda: probe().generate_next(output, fake),
                          lambda: probe().accept_base(output),
                          lambda: probe().retry_pose(output, "idle[0]")):
            with pytest.raises(probe().ProbeError, match="另一个进程"):
                operation()
        assert not fake.calls
        _, stderr = process.communicate("\n", timeout=30)
        assert process.returncode == 0, stderr
        assert read_state(output)["请求次数"] == 1
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=10)


def run_cli(cwd, *args):
    env = dict(os.environ)
    env.pop("OPENAI_API_KEY", None)
    env["PYTHONUTF8"] = "1"
    return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=cwd, env=env,
                          input="", capture_output=True, text=True, encoding="utf-8", timeout=30)


def test_cli_help_prepare_without_key_and_noninteractive_generate(prepared, tmp_path):
    photo, output, _ = prepared
    help_result = run_cli(tmp_path, "--help")
    assert help_result.returncode == 0 and "代表姿势" in help_result.stdout
    result = run_cli(tmp_path, "prepare", "--photo", str(photo), "--output", str(tmp_path / "命令结果"))
    assert result.returncode == 0, result.stderr
    result = run_cli(tmp_path, "generate", "--output", str(output))
    assert result.returncode != 0 and "密钥" in result.stderr
    assert read_state(output)["请求次数"] == 0
    assert "--key" not in help_result.stdout
