"""Mock implementations for local development and tests."""

from __future__ import annotations

from typing import List

from .email_relay import EmailPayload, EmailTransport, MessagePreview, RelayResult
from .oauth import OAuthStatus
from .storage import MemoryTokenStore, TokenBundle


class StubEmailTransport(EmailTransport):
    """In-memory transport used for offline testing."""

    def __init__(self) -> None:
        self.sent: List[EmailPayload] = []
        self.messages: List[MessagePreview] = []

    async def send(self, payload: EmailPayload, oauth_status: OAuthStatus) -> RelayResult:
        self.sent.append(payload)
        return RelayResult(accepted=True, dry_run=False, detail="Stub transport accepted message.")

    async def list_messages(self, limit: int = 10) -> List[MessagePreview]:
        return self.messages[:limit]


def build_memory_token_store() -> MemoryTokenStore:
    """Return a memory token store seeded with placeholder tokens for tests."""

    bundle = TokenBundle(access_token="stub-token", refresh_token="stub-refresh", expires_at=None)
    return MemoryTokenStore(initial=bundle)
