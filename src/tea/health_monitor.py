"""Recurring self-health monitor for Tiny Email App."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from .config import TeaSettings
from .email_relay import EmailPayload, EmailTransport
from .health import HealthReporter, HealthSnapshot
from .oauth import AuthenticationState, OAuthClient

_LOGGER = logging.getLogger(__name__)


class HealthMonitor:
    """Periodically run self-health checks and surface actionable guidance."""

    def __init__(
        self,
        settings: TeaSettings,
        reporter: HealthReporter,
        oauth_client: OAuthClient,
        transport: EmailTransport,
    ) -> None:
        self._settings = settings
        self._reporter = reporter
        self._oauth_client = oauth_client
        self._transport = transport
        self._stop_event = asyncio.Event()
        self._task: Optional[asyncio.Task] = None
        self._current_interval = settings.health_monitor_interval_seconds
        self._consecutive_unhealthy = 0

    @property
    def current_interval(self) -> int:
        return self._current_interval

    async def start(self) -> None:
        if not self._settings.health_monitor_enabled or self._task:
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run(), name="tea.health_monitor")

    async def stop(self) -> None:
        if not self._task:
            return
        self._stop_event.set()
        await self._task
        self._task = None

    async def _run(self) -> None:
        while not self._stop_event.is_set():
            await self.run_once()
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self._current_interval)
            except asyncio.TimeoutError:
                continue

    async def run_once(self) -> None:
        snapshot = await self._reporter.snapshot()
        advice = self._build_actionable_advice(snapshot)
        self._current_interval = self._determine_next_interval(snapshot)
        _LOGGER.info(
            "self_health_check",
            extra={
                "healthy": snapshot.healthy,
                "auth_state": snapshot.authentication.state,
                "auth_message": snapshot.authentication.message,
                "next_interval_seconds": self._current_interval,
                "advice": advice,
            },
        )
        await self._maybe_notify(snapshot, advice)

    def _determine_next_interval(self, snapshot: HealthSnapshot) -> int:
        if snapshot.healthy:
            self._consecutive_unhealthy = 0
            increased = max(
                self._settings.health_monitor_interval_seconds,
                int(self._current_interval * 1.5),
            )
            return min(self._settings.health_monitor_max_interval_seconds, increased)

        self._consecutive_unhealthy += 1
        severity = self._severity_from_state(snapshot.authentication.state)
        base_target = self._settings.health_monitor_interval_seconds // severity
        if base_target == 0:
            base_target = self._settings.health_monitor_min_interval_seconds
        base_target = max(base_target, 1)
        if self._consecutive_unhealthy > 1:
            base_target = max(base_target // 2, self._settings.health_monitor_min_interval_seconds)
        target = max(
            self._settings.health_monitor_min_interval_seconds,
            min(base_target, self._settings.health_monitor_interval_seconds),
        )
        if self._settings.health_notification_enabled and not self._has_addresses():
            return self._settings.health_monitor_min_interval_seconds
        return target

    def _severity_from_state(self, state: AuthenticationState) -> int:
        if state == AuthenticationState.ERROR:
            return 3
        if state == AuthenticationState.NEEDS_BROWSER:
            return 2
        return 1

    def _build_actionable_advice(self, snapshot: HealthSnapshot) -> str:
        if snapshot.healthy:
            return "System healthy. No action required."

        state = snapshot.authentication.state
        if state == AuthenticationState.NEEDS_BROWSER:
            return "Open the noVNC session and complete the provider sign-in to refresh OAuth credentials."
        if state == AuthenticationState.UNAUTHENTICATED:
            return "Review OAuth client credentials or provide a valid refresh token in the mounted secrets store."
        if state == AuthenticationState.ERROR:
            return "Inspect TEA logs and provider status; retries failed and manual intervention is required."
        return "Review the authentication status and confirm provider connectivity."

    async def _maybe_notify(self, snapshot: HealthSnapshot, advice: str) -> None:
        if not self._settings.health_notification_enabled:
            return
        sender = self._settings.health_notification_sender
        recipient = self._settings.health_notification_recipient
        if not self._has_addresses():
            _LOGGER.debug("health_notification_skipped", extra={"reason": "missing_addresses"})
            return
        if self._settings.dry_run:
            _LOGGER.info(
                "health_notification_dry_run",
                extra={"sender": sender, "recipient": recipient, "advice": advice},
            )
            return

        status = self._oauth_client.get_status()
        payload = EmailPayload(
            sender=sender,
            recipient=recipient,
            subject=self._compose_subject(snapshot),
            body=self._compose_body(snapshot, advice),
        )
        try:
            result = await self._transport.send(payload, status)
            _LOGGER.info(
                "health_notification_sent",
                extra={"accepted": result.accepted, "detail": result.detail},
            )
        except (asyncio.TimeoutError, ConnectionError) as exc:
            _LOGGER.warning("health_notification_failed", extra={"error": str(exc), "type": type(exc).__name__})
        except Exception as exc:  # pragma: no cover - unexpected error
            _LOGGER.exception("health_notification_failed_unexpected", extra={"error": str(exc), "type": type(exc).__name__})

    def _has_addresses(self) -> bool:
        return bool(self._settings.health_notification_sender and self._settings.health_notification_recipient)

    def _compose_subject(self, snapshot: HealthSnapshot) -> str:
        prefix = "Healthy" if snapshot.healthy else "Attention required"
        return f"TEA self-health: {prefix}"

    def _compose_body(self, snapshot: HealthSnapshot, advice: str) -> str:
        timestamp = datetime.fromtimestamp(snapshot.timestamp, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S %Z")
        state = snapshot.authentication.state
        message = snapshot.authentication.message or "(no additional details)"
        next_run = self._current_interval
        lines = [
            "Tiny Email App self-health report",
            f"Timestamp: {timestamp}",
            f"Healthy: {snapshot.healthy}",
            f"Authentication state: {state}",
            f"Authentication detail: {message}",
            f"Relay send enabled: {snapshot.relay_send_enabled}",
            f"Relay query enabled: {snapshot.relay_query_enabled}",
            f"Dry run: {snapshot.dry_run}",
            "",
            "Recommended action:",
            advice,
            "",
            f"Next health check scheduled in ~{next_run} seconds.",
        ]
        return "\n".join(lines)