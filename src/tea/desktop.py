"""Runtime helpers for managing the virtual desktop/noVNC stack."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

from .config import TeaSettings

_LOGGER = logging.getLogger(__name__)


@dataclass
class DesktopConfig:
    """Configuration for the virtual desktop environment."""

    enabled: bool
    password_required: bool
    password: Optional[str]
    display: str = ":0"
    geometry: str = "1280x800x24"
    vnc_port: int = 5900
    web_port: int = 6080
    chromium_url: str = "https://example.com"
    runtime_dir: Path = field(default_factory=lambda: Path("/tmp"))
    web_root: Path = field(default_factory=lambda: Path("/usr/share/novnc"))
    popen: Callable[..., subprocess.Popen] = subprocess.Popen

    def __post_init__(self) -> None:
        if self.password_required and not self.password:
            raise ValueError("noVNC password enforcement requested but no password provided.")
        if not self.display.startswith(":"):
            raise ValueError("Display must be in format ':<number>'.")

    @property
    def display_id(self) -> str:
        return self.display.lstrip(":")

    @property
    def lock_path(self) -> Path:
        return self.runtime_dir / f".X{self.display_id}-lock"

    @property
    def socket_path(self) -> Path:
        return (self.runtime_dir / ".X11-unix") / f"X{self.display_id}"


class DesktopLauncher:
    """Launch and monitor the suite of processes powering the remote desktop."""

    def __init__(self, config: DesktopConfig) -> None:
        self.config = config
        self._processes: List[subprocess.Popen] = []

    def _spawn(self, args: Sequence[str], name: str, env: Optional[Dict[str, str]] = None) -> None:
        try:
            popen_env = env or os.environ.copy()
            proc = self.config.popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=popen_env)
            self._processes.append(proc)
            _LOGGER.debug("Started %s with args: %s", name, " ".join(args))
        except FileNotFoundError:
            _LOGGER.warning("Executable '%s' not found; skipping %s startup.", args[0], name)
        except Exception as exc:  # pragma: no cover - defensive logging
            _LOGGER.exception("Failed to start %s: %s", name, exc)

    def _is_process_alive(self, pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:  # pragma: no cover - rare but possible
            return True
        return True

    def _prepare_display(self) -> bool:
        lock = self.config.lock_path
        socket = self.config.socket_path
        if lock.exists():
            try:
                pid = int(lock.read_text().strip())
            except ValueError:
                pid = None
            if pid and self._is_process_alive(pid):
                _LOGGER.info("Display %s already active with pid %s", self.config.display, pid)
                return True
            _LOGGER.info("Removing stale X lock for display %s", self.config.display)
            lock.unlink(missing_ok=True)
        if socket.exists():
            socket.unlink(missing_ok=True)
        socket.parent.mkdir(parents=True, exist_ok=True)
        return False

    def _x11vnc_args(self) -> List[str]:
        args = [
            "x11vnc",
            "-display",
            self.config.display,
            "-forever",
            "-shared",
            "-rfbport",
            str(self.config.vnc_port),
        ]
        if self.config.password_required:
            args.extend(["-passwd", self.config.password or ""])
        else:
            args.append("-nopw")
        return args

    def _websockify_args(self) -> List[str]:
        return [
            "websockify",
            "--web",
            str(self.config.web_root),
            f"0.0.0.0:{self.config.web_port}",
            f"localhost:{self.config.vnc_port}",
        ]

    def _find_binary(self, *candidates: str) -> Optional[str]:
        for candidate in candidates:
            path = shutil.which(candidate)
            if path:
                return path
        return None

    def _chromium_args(self) -> Optional[List[str]]:
        binary = self._find_binary("chromium", "chromium-browser", "google-chrome", "chromium-headless")
        if not binary:
            return None
        return [
            binary,
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-features=Translate",
            "--autoplay-policy=no-user-gesture-required",
            "--force-color-profile=srgb",
            "--window-position=0,0",
            "--start-maximized",
            "--no-first-run",
            self.config.chromium_url,
        ]

    def _terminal_args(self) -> Optional[List[str]]:
        binary = self._find_binary("x-terminal-emulator", "xterm", "lxterminal")
        if not binary:
            return None
        if os.path.basename(binary) == "xterm":
            return [binary, "-fa", "Monospace", "-fs", "11"]
        return [binary]

    def start(self) -> None:
        if not self.config.enabled:
            _LOGGER.info("noVNC disabled via configuration; skipping desktop startup")
            return

        display_active = self._prepare_display()
        if not display_active:
            self._spawn(
                [
                    "Xvfb",
                    self.config.display,
                    "-ac",
                    "-screen",
                    "0",
                    self.config.geometry,
                ],
                name="Xvfb",
            )
            desktop_env = os.environ.copy()
            desktop_env["DISPLAY"] = self.config.display
            self._spawn(["fluxbox"], name="fluxbox", env=desktop_env)
        else:
            _LOGGER.info("Reusing existing X display %s", self.config.display)

        self._spawn(self._x11vnc_args(), name="x11vnc")
        self._spawn(self._websockify_args(), name="websockify")

        terminal_args = self._terminal_args()
        if terminal_args:
            terminal_env = os.environ.copy()
            terminal_env["DISPLAY"] = self.config.display
            self._spawn(terminal_args, name="terminal", env=terminal_env)
        else:
            _LOGGER.info("Terminal emulator not found; desktop will start without a shell window")

        chromium_args = self._chromium_args()
        if chromium_args:
            chromium_env = os.environ.copy()
            chromium_env["DISPLAY"] = self.config.display
            chromium_env.setdefault("XDG_RUNTIME_DIR", str(self.config.runtime_dir))
            self._spawn(chromium_args, name="chromium", env=chromium_env)
        else:
            _LOGGER.info("Chromium binary not found; skipping browser autostart")

    def stop(self) -> None:
        for proc in self._processes:
            if proc.poll() is not None:
                continue
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
            except Exception:  # pragma: no cover - defensive
                _LOGGER.exception("Error while stopping process %s", proc.pid)
        self._processes.clear()

    @contextmanager
    def running(self):
        self.start()
        try:
            yield
        finally:
            self.stop()


def build_desktop_config(settings: TeaSettings) -> DesktopConfig:
    """Helper to translate application settings into a desktop configuration."""

    chromium_url = os.getenv("TEA_CHROMIUM_URL", "https://example.com")
    runtime_dir = Path(os.getenv("TEA_RUNTIME_DIR", "/tmp"))
    web_root = Path(os.getenv("TEA_NOVNC_WEB_ROOT", "/usr/share/novnc"))
    return DesktopConfig(
        enabled=settings.novnc_enabled,
        password_required=settings.noVNC_password_required,
        password=settings.novnc_password,
        display=settings.novnc_display,
        geometry=settings.novnc_geometry,
        vnc_port=settings.novnc_vnc_port,
        web_port=settings.novnc_web_port,
        chromium_url=chromium_url,
        runtime_dir=runtime_dir,
        web_root=web_root,
    )