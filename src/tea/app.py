"""FastAPI application factory for Tiny Email App."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import structlog
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import TeaSettings, get_settings
from .email_relay import EmailPayload, EmailRelayService, EmailTransport, MessagePreview, RelayResult, SMTPOAuthTransport
from .health import HealthReporter
from .oauth import OAuthClient
from .storage import FileTokenStore, MemoryTokenStore, TokenStore
from .stubs import StubEmailTransport, build_memory_token_store


@dataclass
class AppContainer:
    settings: TeaSettings
    oauth_client: OAuthClient
    relay_service: EmailRelayService
    health_reporter: HealthReporter


def configure_logging(debug: bool) -> None:
    """Configure structlog for consistent JSON/text output."""

    timestamper = structlog.processors.TimeStamper(fmt="iso")
    processors = [
        timestamper,
        structlog.processors.add_log_level,
        structlog.processors.EventRenamer("message"),
        structlog.dev.ConsoleRenderer() if debug else structlog.processors.JSONRenderer(),
    ]
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(logging.DEBUG if debug else logging.INFO),
        cache_logger_on_first_use=True,
    )


def build_token_store(settings: TeaSettings) -> TokenStore:
    if settings.mock_mode:
        return build_memory_token_store()
    if settings.secret_store_path:
        path = Path(settings.secret_store_path)
        if path.is_dir():
            path = path / "tokens.json"
        return FileTokenStore(path=path)
    return MemoryTokenStore()


def build_transport(settings: TeaSettings, oauth_client: OAuthClient) -> EmailTransport:
    if settings.mock_mode:
        return StubEmailTransport()
    return SMTPOAuthTransport(settings=settings, oauth_client=oauth_client)


def create_app(settings: Optional[TeaSettings] = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.debug)

    token_store = build_token_store(settings)
    oauth_client = OAuthClient(settings=settings, store=token_store)
    transport = build_transport(settings, oauth_client)
    relay_service = EmailRelayService(settings=settings, transport=transport)
    health_reporter = HealthReporter(settings=settings, oauth=oauth_client)
    container = AppContainer(
        settings=settings,
        oauth_client=oauth_client,
        relay_service=relay_service,
        health_reporter=health_reporter,
    )

    app = FastAPI(title="Tiny Email App", version="0.1.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.state.container = container

    def get_container(request: Request) -> AppContainer:
        return request.app.state.container

    @app.get("/health")
    async def health(container: AppContainer = Depends(get_container)) -> JSONResponse:
        payload = await container.health_reporter.as_dict()
        return JSONResponse(payload)

    @app.get("/oauth/status")
    async def oauth_status(container: AppContainer = Depends(get_container)) -> JSONResponse:
        status = container.oauth_client.get_status()
        payload = {
            "state": status.state,
            "message": status.message,
            "expires_at": status.expires_at,
            "provider": status.provider,
        }
        return JSONResponse(payload)

    @app.post("/oauth/refresh")
    async def oauth_refresh(container: AppContainer = Depends(get_container)) -> JSONResponse:
        status = await container.oauth_client.refresh_access_token()
        payload = {
            "state": status.state,
            "message": status.message,
            "expires_at": status.expires_at,
            "provider": status.provider,
        }
        return JSONResponse(payload)

    @app.post("/relay/send")
    async def relay_send(payload: EmailPayload, container: AppContainer = Depends(get_container)) -> JSONResponse:
        status = container.oauth_client.get_status()
        result = await container.relay_service.send_email(payload, status)
        if not result.accepted:
            raise HTTPException(status_code=503, detail=result.detail)
        return JSONResponse(result.__dict__)

    @app.get("/relay/messages")
    async def relay_messages(limit: int = 10, container: AppContainer = Depends(get_container)) -> list[MessagePreview]:
        messages = await container.relay_service.list_messages(limit=limit)
        return messages

    return app
