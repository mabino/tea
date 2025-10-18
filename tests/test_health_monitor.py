import time

import pytest

from tea.config import TeaSettings
from tea.email_relay import EmailPayload, RelayResult
from tea.health import HealthSnapshot
from tea.health_monitor import HealthMonitor
from tea.oauth import AuthenticationState, OAuthStatus


class DummyReporter:
    def __init__(self, snapshots):
        self._snapshots = list(snapshots)
        self._index = 0

    async def snapshot(self):
        snapshot = self._snapshots[self._index]
        if self._index < len(self._snapshots) - 1:
            self._index += 1
        return snapshot


class DummyOAuthClient:
    def __init__(self, status: OAuthStatus):
        self._status = status

    def get_status(self) -> OAuthStatus:
        return self._status


class DummyTransport:
    def __init__(self):
        self.payloads = []

    async def send(self, payload: EmailPayload, oauth_status: OAuthStatus) -> RelayResult:
        self.payloads.append(payload)
        return RelayResult(accepted=True, dry_run=False, detail="sent")


def build_snapshot(healthy: bool, state: AuthenticationState, message: str = "") -> HealthSnapshot:
    status = OAuthStatus(state=state, message=message, provider="example")
    return HealthSnapshot(
        healthy=healthy,
        authentication=status,
        relay_send_enabled=True,
        relay_query_enabled=False,
        dry_run=False,
        timestamp=time.time(),
    )


@pytest.mark.asyncio
async def test_monitor_notifies_and_adjusts_interval(caplog):
    settings = TeaSettings(
        mock_mode=True,
        oauth_client_id="client",
        oauth_token_endpoint="https://example.com/token",
        health_monitor_interval_seconds=300,
        health_monitor_min_interval_seconds=30,
        health_notification_sender="alerts@example.com",
        health_notification_recipient="ops@example.com",
    )

    snapshot = build_snapshot(False, AuthenticationState.NEEDS_BROWSER, "Sign-in required")
    reporter = DummyReporter([snapshot])
    transport = DummyTransport()
    oauth_client = DummyOAuthClient(snapshot.authentication)
    monitor = HealthMonitor(settings, reporter, oauth_client, transport)

    caplog.set_level("INFO", logger="tea.health_monitor")

    await monitor.run_once()

    assert monitor.current_interval == 150  # 300 base / 2 severity factor
    assert len(transport.payloads) == 1
    payload = transport.payloads[0]
    assert "Attention required" in payload.subject
    assert "noVNC" in payload.body
    assert any(record.msg == "self_health_check" for record in caplog.records)


@pytest.mark.asyncio
async def test_monitor_recovers_interval_when_healthy():
    settings = TeaSettings(
        mock_mode=True,
        oauth_client_id="client",
        oauth_token_endpoint="https://example.com/token",
        health_monitor_interval_seconds=200,
        health_monitor_min_interval_seconds=20,
        health_monitor_max_interval_seconds=400,
        health_notification_sender="alerts@example.com",
        health_notification_recipient="ops@example.com",
    )

    healthy = build_snapshot(True, AuthenticationState.AUTHENTICATED, "OK")
    reporter = DummyReporter([healthy, healthy])
    transport = DummyTransport()
    oauth_client = DummyOAuthClient(healthy.authentication)
    monitor = HealthMonitor(settings, reporter, oauth_client, transport)

    await monitor.run_once()
    assert monitor.current_interval == 300  # 200 * 1.5 but capped by max 400

    await monitor.run_once()
    assert monitor.current_interval == 400  # capped by max interval

    assert len(transport.payloads) == 2  # healthy notifications still sent


@pytest.mark.asyncio
async def test_monitor_skips_notification_without_addresses(caplog):
    settings = TeaSettings(
        mock_mode=True,
        oauth_client_id="client",
        oauth_token_endpoint="https://example.com/token",
        health_notification_enabled=True,
        health_monitor_interval_seconds=120,
        health_monitor_min_interval_seconds=30,
    )

    unhealthy = build_snapshot(False, AuthenticationState.ERROR, "Transport failure")
    reporter = DummyReporter([unhealthy])
    transport = DummyTransport()
    oauth_client = DummyOAuthClient(unhealthy.authentication)
    monitor = HealthMonitor(settings, reporter, oauth_client, transport)

    caplog.set_level("DEBUG", logger="tea.health_monitor")

    await monitor.run_once()

    assert monitor.current_interval == settings.health_monitor_min_interval_seconds
    assert transport.payloads == []
    assert any(
        record.msg == "health_notification_skipped" and getattr(record, "reason", None) == "missing_addresses"
        for record in caplog.records
    )