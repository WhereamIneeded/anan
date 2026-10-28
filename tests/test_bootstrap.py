"""验证首次准备、离线重启、损坏环境修复和失败后的重试。"""

import io
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def manager():
    import importlib.util
    path = Path(__file__).resolve().parents[1] / "scripts/管理.py"
    spec = importlib.util.spec_from_file_location("anan_bootstrap", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def project(tmp_path):
    (tmp_path / "requirements.lock").write_text("组件==1\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text('version = "1"\n', encoding="utf-8")
    return tmp_path


def test_first_prepare_uses_selected_interpreter_and_offline_restart_skips_pip(manager, project, monkeypatch):
    commands = []
    python = project / ".venv/Scripts/python.exe"

    def run(command, root, log):
        commands.append(command)
        if "venv" in command:
            python.parent.mkdir(parents=True)
            python.touch()

    monkeypatch.setattr(manager, "run_checked", run)
    assert manager.prepare_environment(project, io.StringIO()) == python
    assert commands[0][:3] == [manager.sys.executable, "-m", "venv"]
    assert any("pip" in command for command in commands)
    commands.clear()
    manager.prepare_environment(project, io.StringIO())
    assert len(commands) == 1 and "-c" in commands[0]
    assert not any("pip" in command or "pytest" in command for command in commands)


def test_failed_install_does_not_mark_ready_and_next_launch_retries(manager, project, monkeypatch):
    python = project / ".venv/Scripts/python.exe"
    python.parent.mkdir(parents=True)
    python.touch()
    marker = project / ".venv/安安依赖.sha256"
    marker.write_text("旧版签名", encoding="utf-8")

    def fail(command, root, log):
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(manager, "run_checked", fail)
    with pytest.raises(subprocess.CalledProcessError):
        manager.prepare_environment(project, io.StringIO())
    assert not marker.exists()
    commands = []
    monkeypatch.setattr(manager, "run_checked", lambda command, root, log: commands.append(command))
    manager.prepare_environment(project, io.StringIO())
    assert any("pip" in command for command in commands)
    assert marker.read_text(encoding="utf-8") == manager.environment_signature(project)


def test_missing_components_reinstall_even_when_signature_matches(manager, project, monkeypatch):
    python = project / ".venv/Scripts/python.exe"
    python.parent.mkdir(parents=True)
    python.touch()
    (project / ".venv/安安依赖.sha256").write_text(manager.environment_signature(project), encoding="utf-8")
    commands = []

    def run(command, root, log):
        commands.append(command)
        if len(commands) == 1:
            raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(manager, "run_checked", run)
    manager.prepare_environment(project, io.StringIO())
    assert "pip" in commands[1]


def test_dependency_change_invalidates_cached_environment(manager, project):
    before = manager.environment_signature(project)
    (project / "requirements.lock").write_text("组件==2\n", encoding="utf-8")
    assert manager.environment_signature(project) != before


def test_start_reports_immediate_failure_instead_of_silently_closing(manager, project, monkeypatch):
    (project / "build").mkdir()
    monkeypatch.setattr(manager.subprocess, "DETACHED_PROCESS", 8, raising=False)
    monkeypatch.setattr(manager.subprocess, "CREATE_NEW_PROCESS_GROUP", 512, raising=False)
    monkeypatch.setattr(manager.subprocess, "Popen", lambda *args, **kwargs: SimpleNamespace(wait=lambda timeout: 1))
    with pytest.raises(RuntimeError, match="启动日志"):
        manager.launch(project / ".venv/Scripts/python.exe", project)
