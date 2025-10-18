import asyncio

import pytest

from tea.config import TeaSettings
from tea.oauth import AuthenticationState, OAuthClient, OAuthStatus
from tea.storage import MemoryTokenStore, TokenBundle


@pytest.mark.asyncio
async def test_status_without_configuration():
    settings = TeaSettings(oauth_client_id=None, oauth_token_endpoint=None)
    oauth = OAuthClient(settings=settings, store=MemoryTokenStore())
    status = oauth.get_status()
    assert status.state is AuthenticationState.UNAUTHENTICATED


@pytest.mark.asyncio
async def test_status_with_access_token():
    settings = TeaSettings(oauth_client_id="client", oauth_token_endpoint="https://example.com/token")
    store = MemoryTokenStore(TokenBundle(access_token="token", refresh_token="refresh", expires_at=None))
    oauth = OAuthClient(settings=settings, store=store)
    status = oauth.get_status()
    assert status.state is AuthenticationState.AUTHENTICATED


@pytest.mark.asyncio
async def test_refresh_without_refresh_token():
    settings = TeaSettings(oauth_client_id="client", oauth_token_endpoint="https://example.com/token")
    oauth = OAuthClient(settings=settings, store=MemoryTokenStore())
    status = await oauth.refresh_access_token()
    assert status.state is AuthenticationState.UNAUTHENTICATED


@pytest.mark.asyncio
async def test_refresh_with_http_error(monkeypatch):
    settings = TeaSettings(oauth_client_id="client", oauth_token_endpoint="https://example.com/token")
    store = MemoryTokenStore(TokenBundle(access_token=None, refresh_token="refresh", expires_at=None))
    oauth = OAuthClient(settings=settings, store=store)

    class DummyResponse:
        status_code = 400

        def json(self):
            return {}

    class DummyClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, *args, **kwargs):
            return DummyResponse()

    monkeypatch.setattr("httpx.AsyncClient", lambda timeout: DummyClient())
    status = await oauth.refresh_access_token()
    assert status.state is AuthenticationState.NEEDS_BROWSER


@pytest.mark.asyncio
async def test_refresh_success(monkeypatch):
    settings = TeaSettings(
        oauth_client_id="client",
        oauth_client_secret="secret",
        oauth_token_endpoint="https://example.com/token",
        oauth_scopes=["scope1"],
    )
    store = MemoryTokenStore(TokenBundle(access_token=None, refresh_token="refresh", expires_at=None))
    oauth = OAuthClient(settings=settings, store=store)

    class DummyResponse:
        status_code = 200

        def json(self):
            return {"access_token": "new-token", "refresh_token": "refresh", "expires_in": 3600}

    class DummyClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, *args, **kwargs):
            return DummyResponse()

    monkeypatch.setattr("httpx.AsyncClient", lambda timeout: DummyClient())
    status = await oauth.refresh_access_token()
    assert status.state is AuthenticationState.AUTHENTICATED


def test_status_needs_browser():
    settings = TeaSettings(oauth_client_id="client", oauth_token_endpoint="https://example.com/token")
    store = MemoryTokenStore(TokenBundle(access_token=None, refresh_token="refresh", expires_at=None))
    oauth = OAuthClient(settings=settings, store=store)
    status = oauth.get_status()
    assert status.state is AuthenticationState.NEEDS_BROWSER
