import asyncio

import pytest

from tea.config import TeaSettings
from tea.email_relay import EmailPayload, EmailRelayService, MessagePreview, SMTPOAuthTransport
from tea.oauth import AuthenticationState, OAuthClient, OAuthStatus
from tea.stubs import StubEmailTransport
from tea.storage import MemoryTokenStore, TokenBundle


@pytest.mark.asyncio
async def test_send_email_dry_run():
    settings = TeaSettings(dry_run=True)
    transport = StubEmailTransport()
    relay = EmailRelayService(settings=settings, transport=transport)
    payload = EmailPayload(sender="alice@example.com", recipient="bob@example.com", subject="Hello", body="Hi")
    status = OAuthStatus(state=AuthenticationState.AUTHENTICATED)
    result = await relay.send_email(payload, status)
    assert result.dry_run is True
    assert not transport.sent


@pytest.mark.asyncio
async def test_send_email_disabled():
    settings = TeaSettings(relay_send_enabled=False)
    transport = StubEmailTransport()
    relay = EmailRelayService(settings=settings, transport=transport)
    payload = EmailPayload(sender="alice@example.com", recipient="bob@example.com", subject="Hello", body="Hi")
    status = OAuthStatus(state=AuthenticationState.AUTHENTICATED)
    result = await relay.send_email(payload, status)
    assert result.accepted is False
    assert not transport.sent


@pytest.mark.asyncio
async def test_list_messages_disabled():
    settings = TeaSettings(relay_query_enabled=False)
    transport = StubEmailTransport()
    transport.messages.append(MessagePreview(id="1", subject="Test", sender="alice@example.com"))
    relay = EmailRelayService(settings=settings, transport=transport)
    messages = await relay.list_messages(limit=5)
    assert messages == []


@pytest.mark.asyncio
async def test_send_email_requires_auth_when_not_dry_run():
    settings = TeaSettings()
    transport = StubEmailTransport()
    relay = EmailRelayService(settings=settings, transport=transport)
    payload = EmailPayload(sender="alice@example.com", recipient="bob@example.com", subject="Hello", body="Hi")
    status = OAuthStatus(state=AuthenticationState.UNAUTHENTICATED)
    result = await relay.send_email(payload, status)
    assert result.accepted is False
    assert not transport.sent


@pytest.mark.asyncio
async def test_smtp_transport_send(monkeypatch):
    settings = TeaSettings(
        smtp_host="smtp.example.com",
        smtp_port=25,
        smtp_use_tls=True,
        oauth_client_id="client",
        oauth_token_endpoint="https://example.com/token",
    )
    store = MemoryTokenStore(TokenBundle(access_token="token", refresh_token="refresh", expires_at=None))
    oauth = OAuthClient(settings=settings, store=store)
    transport = SMTPOAuthTransport(settings=settings, oauth_client=oauth)

    class DummySMTP:
        def __init__(self, host, port):
            self.host = host
            self.port = port
            self.commands = []
            self.messages = []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def starttls(self):
            self.commands.append("starttls")

        def docmd(self, command, data):
            self.commands.append((command, data))

        def send_message(self, message):
            self.messages.append(message)

    monkeypatch.setattr("smtplib.SMTP", DummySMTP)

    async def immediate(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", immediate)

    payload = EmailPayload(sender="alice@example.com", recipient="bob@example.com", subject="Hello", body="Hi")
    status = oauth.get_status()
    result = await transport.send(payload, status)
    assert result.accepted is True


@pytest.mark.asyncio
async def test_smtp_transport_list_messages(monkeypatch):
    settings = TeaSettings(
        imap_host="imap.example.com",
        imap_port=993,
        oauth_client_id="client",
        oauth_token_endpoint="https://example.com/token",
    )
    store = MemoryTokenStore(TokenBundle(access_token="token", refresh_token="refresh", expires_at=None))
    oauth = OAuthClient(settings=settings, store=store)
    transport = SMTPOAuthTransport(settings=settings, oauth_client=oauth)

    class DummyIMAP:
        def __init__(self, host, port):
            self.host = host
            self.port = port

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def authenticate(self, mechanism, callback):
            self.auth = callback(None)

        def select(self, mailbox):
            self.mailbox = mailbox

        def search(self, charset, criteria):
            return "OK", [b"1 2"]

        def fetch(self, msg_id, query):
            headers = b"From: Carol <carol@example.com>\r\nSubject: Update\r\n"
            return "OK", [(None, headers)]

    monkeypatch.setattr("imaplib.IMAP4_SSL", DummyIMAP)
    async def immediate(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", immediate)

    messages = await transport.list_messages(limit=1)
    assert messages[0].subject == "Update"
