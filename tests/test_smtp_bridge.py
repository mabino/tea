from email.message import EmailMessage

import pytest

from tea.email_relay import EmailPayload, RelayResult
from tea.smtp_bridge import SMTPBridge, SMTPRelayHandler, _extract_body


class DummyRelayService:
    def __init__(self, result: RelayResult):
        self._result = result
        self.payloads = []

    async def send_email(self, payload: EmailPayload, oauth_status):
        self.payloads.append((payload, oauth_status))
        return self._result


class DummyOAuthClient:
    def __init__(self, status):
        self._status = status

    def get_status(self):
        return self._status


class DummyStatus:
    def __init__(self):
        self.state = "authenticated"


class DummyController:
    def __init__(self, handler, hostname, port):
        self.handler = handler
        self.hostname = hostname
        self.port = port
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True


class DummyEnvelope:
    def __init__(self, sender: str, recipient: str, message: EmailMessage):
        self.mail_from = sender
        self.rcpt_tos = [recipient]
        self.content = message.as_bytes()


@pytest.mark.asyncio
async def test_handler_accepts_and_relays(monkeypatch):
    result = RelayResult(accepted=True, dry_run=False, detail="ok")
    relay_service = DummyRelayService(result)
    oauth_client = DummyOAuthClient(DummyStatus())
    handler = SMTPRelayHandler(relay_service, oauth_client)

    msg = EmailMessage()
    msg["Subject"] = "Test"
    msg.set_content("Hello")
    envelope = DummyEnvelope("sender@example.com", "rcpt@example.com", msg)

    response = await handler.handle_DATA(None, None, envelope)
    assert response == "250 Message accepted for delivery"
    payload, status = relay_service.payloads[0]
    assert payload.sender == "sender@example.com"
    assert payload.recipient == "rcpt@example.com"
    assert payload.subject == "Test"
    assert payload.body.strip() == "Hello"
    assert status is oauth_client.get_status()


@pytest.mark.asyncio
async def test_handler_returns_error():
    result = RelayResult(accepted=False, dry_run=False, detail="not accepted")
    relay_service = DummyRelayService(result)
    oauth_client = DummyOAuthClient(DummyStatus())
    handler = SMTPRelayHandler(relay_service, oauth_client)

    msg = EmailMessage()
    msg["Subject"] = "Fail"
    msg.set_content("Nope")
    envelope = DummyEnvelope("sender@example.com", "rcpt@example.com", msg)

    response = await handler.handle_DATA(None, None, envelope)
    assert response == "550 not accepted"


def test_bridge_start_stop(monkeypatch):
    events = {}

    def fake_controller(handler, hostname, port):
        ctrl = DummyController(handler, hostname, port)
        events["controller"] = ctrl
        return ctrl

    monkeypatch.setattr("tea.smtp_bridge.Controller", fake_controller)

    class DummySettings:
        smtp_bridge_enabled = True
        smtp_bridge_host = "0.0.0.0"
        smtp_bridge_port = 2526

    settings = DummySettings()
    relay_service = DummyRelayService(RelayResult(True, False, "ok"))
    oauth_client = DummyOAuthClient(DummyStatus())

    bridge = SMTPBridge(settings, relay_service, oauth_client)

    bridge.start()
    assert bridge.is_running
    ctrl = events["controller"]
    assert ctrl.hostname == "0.0.0.0"
    assert ctrl.port == 2526
    assert ctrl.started

    bridge.stop()
    assert not bridge.is_running
    assert ctrl.stopped


def test_bridge_ignores_when_disabled():
    class DummySettings:
        smtp_bridge_enabled = False
        smtp_bridge_host = "127.0.0.1"
        smtp_bridge_port = 2525

    settings = DummySettings()
    relay_service = DummyRelayService(RelayResult(True, False, "ok"))
    oauth_client = DummyOAuthClient(DummyStatus())

    bridge = SMTPBridge(settings, relay_service, oauth_client)
    bridge.start()
    assert not bridge.is_running


def test_extract_body_prefers_plain_text():
    msg = EmailMessage()
    msg.set_content("Hello plain")
    assert _extract_body(msg) == "Hello plain\n"

    msg_alt = EmailMessage()
    msg_alt.set_content("<p>Hi</p>", subtype="html")
    assert "<p>Hi" in _extract_body(msg_alt)
