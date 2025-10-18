"""OAuth client abstraction for Tiny Email App."""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional

import httpx
from pydantic import BaseModel, Field

from .config import TeaSettings
from .storage import TokenBundle, TokenStore


class AuthenticationState(str, Enum):
    AUTHENTICATED = "authenticated"
    NEEDS_BROWSER = "needs_browser_intervention"
    UNAUTHENTICATED = "unauthenticated"
    ERROR = "error"


@dataclass
class OAuthStatus:
    state: AuthenticationState
    message: str = ""
    expires_at: Optional[float] = None
    provider: Optional[str] = None


class OAuthTokens(BaseModel):
    access_token: str = Field(...)
    refresh_token: Optional[str] = Field(default=None)
    expires_in: Optional[int] = Field(default=None)
    token_type: str = Field(default="Bearer")

    def as_bundle(self) -> TokenBundle:
        expires_at = None
        if self.expires_in is not None:
            expires_at = time.time() + self.expires_in
        return TokenBundle(access_token=self.access_token, refresh_token=self.refresh_token, expires_at=expires_at)


class OAuthClient:
    """Minimal OAuth client that can refresh tokens and report status."""

    def __init__(self, settings: TeaSettings, store: TokenStore) -> None:
        self._settings = settings
        self._store = store
        self._last_error: Optional[str] = None

        if self._settings.oauth_access_token or self._settings.oauth_refresh_token:
            bundle = TokenBundle(
                access_token=self._settings.oauth_access_token,
                refresh_token=self._settings.oauth_refresh_token,
            )
            self._store.save(bundle)

    @property
    def is_configured(self) -> bool:
        required = [self._settings.oauth_client_id, self._settings.oauth_token_endpoint]
        return all(required)

    def get_status(self) -> OAuthStatus:
        bundle = self._store.load()
        if not self.is_configured:
            return OAuthStatus(state=AuthenticationState.UNAUTHENTICATED, message="OAuth client is not fully configured.")

        if bundle.access_token and not self._token_expired(bundle):
            return OAuthStatus(
                state=AuthenticationState.AUTHENTICATED,
                message="Access token available.",
                expires_at=bundle.expires_at,
                provider=self._settings.oauth_tenant,
            )

        if bundle.refresh_token:
            return OAuthStatus(
                state=AuthenticationState.NEEDS_BROWSER,
                message="Browser sign-in required to refresh access token.",
                provider=self._settings.oauth_tenant,
            )

        detail = self._last_error or "No tokens available."
        return OAuthStatus(state=AuthenticationState.UNAUTHENTICATED, message=detail, provider=self._settings.oauth_tenant)

    def get_tokens(self) -> TokenBundle:
        """Expose the persisted token bundle for transports."""

        return self._store.load()

    async def refresh_access_token(self) -> OAuthStatus:
        if not self.is_configured:
            return self.get_status()

        bundle = self._store.load()
        if bundle.refresh_token is None:
            self._last_error = "Missing refresh token."
            return self.get_status()

        payload = {
            "client_id": self._settings.oauth_client_id,
            "client_secret": self._settings.oauth_client_secret,
            "grant_type": "refresh_token",
            "refresh_token": bundle.refresh_token,
        }
        if self._settings.oauth_scopes:
            payload["scope"] = " ".join(self._settings.oauth_scopes)

        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(self._settings.oauth_token_endpoint, data=payload)
            if response.status_code != 200:
                self._last_error = f"Token refresh failed: {response.status_code}"
                return self.get_status()

            data = response.json()
            tokens = OAuthTokens.model_validate(data)
            new_bundle = tokens.as_bundle()
            if new_bundle.refresh_token is None:
                new_bundle.refresh_token = bundle.refresh_token
            self._store.save(new_bundle)
            self._last_error = None

        return self.get_status()

    def _token_expired(self, bundle: TokenBundle) -> bool:
        if bundle.expires_at is None:
            return False
        return bundle.expires_at <= time.time()
