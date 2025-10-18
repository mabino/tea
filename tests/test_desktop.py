import os
import subprocess
from typing import List

import pytest

from tea.config import TeaSettings
from tea.desktop import DesktopConfig, DesktopLauncher, build_desktop_config


class DummyProc:
    def __init__(self, args):
        self.args = list(args)
        self._terminated = False

    def poll(self):
        return None if not self._terminated else 0

    def terminate(self):
        self._terminated = True

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self._terminated = True


class Recorder:
    def __init__(self):
        self.calls: List[List[str]] = []
        self.processes: List[DummyProc] = []
        self.envs: List[dict] = []

    def __call__(self, args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=None):
        command = list(args)
        proc = DummyProc(command)
        self.calls.append(command)
        self.processes.append(proc)
        self.envs.append(dict(env or {}))
        return proc


def test_desktop_config_requires_password():
    with pytest.raises(ValueError):
        DesktopConfig(enabled=True, password_required=True, password=None)


def test_build_desktop_config_from_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("TEA_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setenv("TEA_NOVNC_WEB_ROOT", str(tmp_path / "novnc"))
    monkeypatch.setenv("TEA_CHROMIUM_URL", "https://tea.example/app")
    monkeypatch.setenv("NOVNC_PORT", "7000")
    settings = TeaSettings(
        novnc_enabled=True,
        novnc_password_enabled=True,
        novnc_password="secret",
        novnc_display=":2",
        novnc_geometry="1024x768x24",
        novnc_vnc_port=5905,
    )

    config = build_desktop_config(settings)
    assert config.enabled is True
    assert config.password_required is True
    assert config.password == "secret"
    assert config.display == ":2"
    assert config.geometry == "1024x768x24"
    assert config.vnc_port == 5905
    assert config.web_port == 7000
    assert config.runtime_dir == tmp_path
    assert config.web_root == tmp_path / "novnc"
    assert config.chromium_url == "https://tea.example/app"


def test_launcher_start_and_stop_spawns_processes(tmp_path, monkeypatch):
    recorder = Recorder()
    config = DesktopConfig(
        enabled=True,
        password_required=False,
        password=None,
        runtime_dir=tmp_path,
        web_root=tmp_path,
        popen=recorder,
    )

    def fake_which(binary: str):
        if binary in {"chromium", "chromium-browser", "google-chrome", "chromium-headless"}:
            return "/usr/bin/mock-chromium"
        if binary in {"x-terminal-emulator", "xterm", "lxterminal"}:
            return "/usr/bin/mock-terminal"
        return None

    monkeypatch.setattr("tea.desktop.shutil.which", fake_which)

    launcher = DesktopLauncher(config)
    with launcher.running():
        pass

    commands = {cmd[0] for cmd in recorder.calls}
    assert "Xvfb" in commands
    assert "fluxbox" in commands
    assert "x11vnc" in commands
    assert "websockify" in commands
    assert any(cmd[0] == "/usr/bin/mock-terminal" for cmd in recorder.calls)
    assert any(cmd[0] == "/usr/bin/mock-chromium" for cmd in recorder.calls)

    def env_for(binary: str) -> dict:
        for cmd, env in zip(recorder.calls, recorder.envs):
            if cmd[0] == binary:
                return env
        return {}

    assert env_for("fluxbox").get("DISPLAY") == config.display
    assert env_for("/usr/bin/mock-terminal").get("DISPLAY") == config.display
    chromium_env = env_for("/usr/bin/mock-chromium")
    assert chromium_env.get("DISPLAY") == config.display
    assert chromium_env.get("XDG_RUNTIME_DIR") == str(tmp_path)

    chromium_call = next(cmd for cmd in recorder.calls if cmd[0] == "/usr/bin/mock-chromium")
    assert all(not arg.startswith("--app=") for arg in chromium_call)
    assert config.chromium_url in chromium_call

    assert all(proc._terminated for proc in recorder.processes)
    assert launcher._processes == []


def test_prepare_display_removes_stale_lock(tmp_path, monkeypatch):
    recorder = Recorder()
    config = DesktopConfig(
        enabled=True,
        password_required=False,
        password=None,
        display=":42",
        runtime_dir=tmp_path,
        web_root=tmp_path,
        popen=recorder,
    )

    lock_path = config.lock_path
    lock_path.write_text("12345")
    socket_path = config.socket_path
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    socket_path.touch()

    launcher = DesktopLauncher(config)
    monkeypatch.setattr(DesktopLauncher, "_is_process_alive", lambda self, pid: False)

    assert launcher._prepare_display() is False
    assert not lock_path.exists()
    assert not socket_path.exists()
    assert socket_path.parent.exists()


def test_prepare_display_detects_running_display(tmp_path, monkeypatch):
    config = DesktopConfig(
        enabled=True,
        password_required=False,
        password=None,
        display=":5",
        runtime_dir=tmp_path,
        web_root=tmp_path,
    )

    lock_path = config.lock_path
    lock_path.write_text(str(os.getpid()))

    launcher = DesktopLauncher(config)
    monkeypatch.setattr(DesktopLauncher, "_is_process_alive", lambda self, pid: True)

    assert launcher._prepare_display() is True
    assert lock_path.exists()


def test_x11vnc_args_password_enforced(tmp_path):
    config = DesktopConfig(
        enabled=True,
        password_required=True,
        password="secret",
        runtime_dir=tmp_path,
        web_root=tmp_path,
    )
    launcher = DesktopLauncher(config)

    args = launcher._x11vnc_args()
    assert "-passwd" in args
    assert args[args.index("-passwd") + 1] == "secret"
    assert "-nopw" not in args


def test_x11vnc_args_without_password(tmp_path):
    config = DesktopConfig(
        enabled=True,
        password_required=False,
        password=None,
        runtime_dir=tmp_path,
        web_root=tmp_path,
    )
    launcher = DesktopLauncher(config)

    args = launcher._x11vnc_args()
    assert "-nopw" in args
    assert "-passwd" not in args
