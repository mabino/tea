"""Health reporting utilities."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Dict

from .config import TeaSettings
from .oauth import AuthenticationState, OAuthClient, OAuthStatus


@dataclass
class HealthSnapshot:
    healthy: bool
    authentication: OAuthStatus
    relay_send_enabled: bool
    relay_query_enabled: bool
    dry_run: bool
    timestamp: float


class HealthReporter:
    """Produce cached health snapshots."""

    def __init__(self, settings: TeaSettings, oauth: OAuthClient) -> None:
        self._settings = settings
        self._oauth = oauth
        self._cache: HealthSnapshot | None = None

    async def snapshot(self) -> HealthSnapshot:
        now = time.time()
        if self._cache and (now - self._cache.timestamp) < self._settings.health_status_cache_ttl:
            return self._cache

        auth_status = self._oauth.get_status()
        healthy = auth_status.state == AuthenticationState.AUTHENTICATED
        snapshot = HealthSnapshot(
            healthy=healthy,
            authentication=auth_status,
            relay_send_enabled=self._settings.relay_send_enabled,
            relay_query_enabled=self._settings.relay_query_enabled,
            dry_run=self._settings.dry_run,
            timestamp=now,
        )
        self._cache = snapshot
        return snapshot

    async def as_dict(self) -> Dict[str, object]:
        snap = await self.snapshot()
        return {
            "healthy": snap.healthy,
            "authentication": {
                "state": snap.authentication.state,
                "message": snap.authentication.message,
                "expires_at": snap.authentication.expires_at,
                "provider": snap.authentication.provider,
            },
            "relay": {
                "send_enabled": snap.relay_send_enabled,
                "query_enabled": snap.relay_query_enabled,
            },
            "dry_run": snap.dry_run,
        }
