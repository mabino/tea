# Tiny Email App Copilot Instructions

## Project Overview
- TEA is a FastAPI email relay packaged with an optional noVNC desktop and Playwright-ready Chromium; see src/tea/runtime.py for the container entrypoint that boots both the desktop stack and the API server.
- Configuration flows through TeaSettings in src/tea/config.py (Pydantic BaseSettings with TEA_ prefix); new env flags must be added here and surfaced in README.md.
- OAuth state is centralized in src/tea/oauth.py with TokenStore abstractions from src/tea/storage.py; interact with OAuthClient instead of rolling new HTTP calls.

## Architecture & Conventions
- create_app in src/tea/app.py wires together settings, OAuth, EmailRelayService, HealthReporter, HealthMonitor, and the optional SMTPBridge; integrate new subsystems via the AppContainer and FastAPI lifespan block.
- EmailRelayService (src/tea/email_relay.py) enforces feature flags and dry-run semantics before delegating to transports; extend behaviour here instead of talking to transports directly.
- SMTPOAuthTransport wraps real network I/O, while StubEmailTransport and build_memory_token_store provide deterministic offline behaviour for tests.
- Background health checks live in src/tea/health_monitor.py and rely on HealthReporter snapshots; when adding new health data, update both the reporter and monitor advice paths.
- The desktop launcher in src/tea/desktop.py manages Xvfb, fluxbox, x11vnc, and optional Chromium; reuse DesktopLauncher.running() when coordinating new long-lived processes.
- Logging uses structlog; obtain loggers via structlog.get_logger or structlog.get_logger(__name__) to match existing output.

## Developer Workflows
- Install the project locally with `pip install -e '.[dev,playwright]'`; this pulls Playwright binaries expected by the Docker image and tests.
- Common test run: `pytest --cov=tea --cov-report=term-missing`; the suite mocks network access by flipping TeaSettings(mock_mode=True).
- FastAPI smoke tests in tests/test_app.py rely on httpx.AsyncClient + ASGITransport; mirror this pattern for new endpoints.
- Health monitor tests (tests/test_health_monitor.py) drive the scheduler via manual run_once calls and patched transports; reuse these helpers when altering cadence logic.
- Docker-based validation mirrors CI: `docker compose up --build` starts the API, desktop, and Chromium in one container.
- Workflow changes live in .github/workflows/ci.yml; workflow_dispatch is enabled for manual runs, and the pipeline executes pytest inside the container image.

## Extension Guidelines
- Always route outbound mail through EmailRelayService to honour dry-run and relay flags; calling SMTPOAuthTransport directly will bypass safety checks.
- When introducing new persistence, extend TokenStore or create a dedicated abstraction rather than mixing file I/O into feature code.
- Respect mock_mode in new components (`settings.mock_mode`) so the app stays offline-friendly during tests and local runs.
- Surface user-facing state through HealthReporter.as_dict() or new endpoints rather than accessing private attributes from FastAPI routes.
- If you enable optional services (e.g. SMTP bridge), guard lifecycle hooks with configuration checks and clean up in the FastAPI lifespan shutdown.
