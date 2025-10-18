"""Email relay services for Tiny Email App."""

from __future__ import annotations

import asyncio
import base64
import imaplib
import smtplib
from abc import ABC, abstractmethod
from dataclasses import dataclass
from email.message import EmailMessage
from typing import List

from email_validator import EmailNotValidError, validate_email
from pydantic import BaseModel, Field

from .config import TeaSettings
from .oauth import AuthenticationState, OAuthClient, OAuthStatus


class EmailPayload(BaseModel):
    sender: str = Field(..., description="Envelope from address.")
    recipient: str = Field(..., description="Envelope to address.")
    subject: str = Field(..., description="Subject line.")
    body: str = Field(..., description="Plain text body content.")

    def validate_addresses(self) -> None:
        for attr in ("sender", "recipient"):
            value = getattr(self, attr)
            try:
                validate_email(value, check_deliverability=False)
            except EmailNotValidError as exc:  # pragma: no cover - handled via validation
                raise ValueError(f"Invalid email: {value}") from exc


class MessagePreview(BaseModel):
    id: str
    subject: str
    sender: str


@dataclass
class RelayResult:
    accepted: bool
    dry_run: bool
    detail: str


class EmailTransport(ABC):
    """Abstraction around outbound and inbound email operations."""

    @abstractmethod
    async def send(self, payload: EmailPayload, oauth_status: OAuthStatus) -> RelayResult:
        ...

    @abstractmethod
    async def list_messages(self, limit: int = 10) -> List[MessagePreview]:
        ...


class SMTPOAuthTransport(EmailTransport):
    """SMTP transport that performs XOAUTH2 authentication."""

    def __init__(self, settings: TeaSettings, oauth_client: OAuthClient) -> None:
        self._settings = settings
        self._oauth_client = oauth_client

    async def send(self, payload: EmailPayload, oauth_status: OAuthStatus) -> RelayResult:
        payload.validate_addresses()
        message = EmailMessage()
        message["From"] = payload.sender
        message["To"] = payload.recipient
        message["Subject"] = payload.subject
        message.set_content(payload.body)

        bundle = self._oauth_client.get_tokens()
        if not bundle.access_token:
            return RelayResult(accepted=False, dry_run=False, detail="No access token available.")

        def _send_sync() -> RelayResult:
            with smtplib.SMTP(self._settings.smtp_host, self._settings.smtp_port) as smtp:
                if self._settings.smtp_use_tls:
                    smtp.starttls()
                auth_string = self._build_xoauth2(payload.sender, bundle.access_token)
                smtp.docmd("AUTH", "XOAUTH2 " + auth_string)
                smtp.send_message(message)
            return RelayResult(accepted=True, dry_run=False, detail="Email sent successfully.")

        return await asyncio.to_thread(_send_sync)

    async def list_messages(self, limit: int = 10) -> List[MessagePreview]:
        bundle = self._oauth_client.get_tokens()
        if not bundle.access_token:
            return []

        def _list_sync() -> List[MessagePreview]:
            results: List[MessagePreview] = []
            if not self._settings.imap_host:
                return results
            with imaplib.IMAP4_SSL(self._settings.imap_host, self._settings.imap_port) as client:
                auth_string = self._build_xoauth2("", bundle.access_token)
                client.authenticate("XOAUTH2", lambda _: auth_string.encode())
                client.select("INBOX")
                typ, data = client.search(None, "ALL")
                if typ != "OK":
                    return results
                message_ids = data[0].split()
                for msg_id in reversed(message_ids[-limit:]):
                    typ, msg_data = client.fetch(msg_id, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT)])")
                    if typ != "OK":
                        continue
                    header_bytes = msg_data[0][1]
                    header = header_bytes.decode("utf-8", errors="replace")
                    sender = ""
                    subject = ""
                    for line in header.splitlines():
                        if line.lower().startswith("from:"):
                            sender = line.split(":", 1)[1].strip()
                        if line.lower().startswith("subject:"):
                            subject = line.split(":", 1)[1].strip()
                    results.append(
                        MessagePreview(id=msg_id.decode("utf-8"), subject=subject, sender=sender)
                    )
            return results

        return await asyncio.to_thread(_list_sync)

    def _build_xoauth2(self, username: str, access_token: str) -> str:
        auth_string = f"user={username}\1auth=Bearer {access_token}\1\1"
        return base64.b64encode(auth_string.encode()).decode()


class EmailRelayService:
    """Coordinates relay behaviour with configuration flags."""

    def __init__(self, settings: TeaSettings, transport: EmailTransport) -> None:
        self._settings = settings
        self._transport = transport

    async def send_email(self, payload: EmailPayload, oauth_status: OAuthStatus) -> RelayResult:
        if not self._settings.relay_send_enabled:
            return RelayResult(accepted=False, dry_run=False, detail="Relay submission disabled.")

        if oauth_status.state != AuthenticationState.AUTHENTICATED and not self._settings.dry_run:
            return RelayResult(accepted=False, dry_run=False, detail="OAuth authentication required.")

        if self._settings.dry_run:
            payload.validate_addresses()
            return RelayResult(accepted=True, dry_run=True, detail="Dry run enabled; email not sent.")

        return await self._transport.send(payload, oauth_status)

    async def list_messages(self, limit: int = 10) -> List[MessagePreview]:
        if not self._settings.relay_query_enabled:
            return []
        return await self._transport.list_messages(limit=limit)
