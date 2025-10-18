"""Container entrypoint orchestrating the desktop stack and API server."""

from __future__ import annotations

import logging
from contextlib import ExitStack

import uvicorn

from .app import create_app
from .config import TeaSettings, get_settings
from .desktop import DesktopLauncher, build_desktop_config

_LOGGER = logging.getLogger(__name__)


def run_server(settings: TeaSettings) -> None:
    """Start the FastAPI application via uvicorn."""

    app = create_app(settings)
    uvicorn.run(
        app,
        host=settings.app_host,
        port=settings.app_port,
        log_level="debug" if settings.debug else "info",
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = get_settings()
    desktop_config = build_desktop_config(settings)
    launcher = DesktopLauncher(desktop_config)

    with ExitStack() as stack:
        stack.enter_context(launcher.running())
        run_server(settings)


if __name__ == "__main__":
    main()
