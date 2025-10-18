"""SMTP bridge that forwards messages into the relay service."""

from __future__ import annotations

from email import message_from_bytes
from email.message import EmailMessage
from email.policy import default
from typing import Optional

import structlog
from aiosmtpd.controller import Controller

from .config import TeaSettings
from .email_relay import EmailPayload, EmailRelayService
from .oauth import OAuthClient

_LOGGER = structlog.get_logger(__name__)


class SMTPRelayHandler:
    """aiosmtpd handler that routes inbound messages through the relay service."""

    def __init__(self, relay_service: EmailRelayService, oauth_client: OAuthClient) -> None:
        self._relay_service = relay_service
        self._oauth_client = oauth_client

    async def handle_DATA(self, server, session, envelope) -> str:  # noqa: N802 (aiosmtpd API)
        message = message_from_bytes(envelope.content, policy=default)
        sender = envelope.mail_from or ""
        recipient = envelope.rcpt_tos[0] if envelope.rcpt_tos else ""
        payload = EmailPayload(
            sender=sender,
            recipient=recipient,
            subject=message.get("Subject", ""),
            body=_extract_body(message),
        )
        status = self._oauth_client.get_status()
        result = await self._relay_service.send_email(payload, status)
        if result.accepted:
            return "250 Message accepted for delivery"
        _LOGGER.warning("smtp_bridge_relay_failed", detail=result.detail)
        return f"550 {result.detail}"


class SMTPBridge:
    """Lifecycle wrapper around the aiosmtpd controller."""

    def __init__(
        self,
        settings: TeaSettings,
        relay_service: EmailRelayService,
        oauth_client: OAuthClient,
    ) -> None:
        self._settings = settings
        self._relay_service = relay_service
        self._oauth_client = oauth_client
        self._controller: Optional[Controller] = None

    def start(self) -> None:
        if not self._settings.smtp_bridge_enabled or self._controller is not None:
            return
        handler = SMTPRelayHandler(self._relay_service, self._oauth_client)
        self._controller = Controller(
            handler,
            hostname=self._settings.smtp_bridge_host,
            port=self._settings.smtp_bridge_port,
        )
        self._controller.start()
        _LOGGER.info(
            "smtp_bridge_started",
            host=self._settings.smtp_bridge_host,
            port=self._settings.smtp_bridge_port,
        )

    def stop(self) -> None:
        if self._controller is None:
            return
        self._controller.stop()
        self._controller = None
        _LOGGER.info("smtp_bridge_stopped")

    @property
    def is_running(self) -> bool:
        return self._controller is not None


def _extract_body(message: EmailMessage) -> str:
    if message.is_multipart():
        part = message.get_body(preferencelist=("plain", "html"))
        if part is not None:
            try:
                return part.get_content()
            except Exception:  # pragma: no cover - defensive
                pass
        payload = message.get_payload(decode=True)
        if isinstance(payload, bytes):
            return payload.decode("utf-8", errors="replace")
        return str(payload or "")
    if message.get_content_disposition() == "attachment":
        return ""
    try:
        return message.get_content()
    except Exception:  # pragma: no cover - defensive
        payload = message.get_payload(decode=True)
        if isinstance(payload, bytes):
            return payload.decode("utf-8", errors="replace")
        return str(payload or "")
