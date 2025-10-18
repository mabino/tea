from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from tea.app import create_app
from tea.config import TeaSettings
from tea.oauth import AuthenticationState, OAuthStatus


@pytest.mark.asyncio
async def test_health_endpoint_reports_flags(monkeypatch):
    settings = TeaSettings(
        mock_mode=True,
        relay_query_enabled=True,
        oauth_client_id="client",
        oauth_token_endpoint="https://example.com/token",
    )

    app = create_app(settings=settings)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")
    payload = response.json()
    assert response.status_code == 200
    assert payload["relay"]["query_enabled"] is True


@pytest.mark.asyncio
async def test_relay_send_accepted(monkeypatch):
    settings = TeaSettings(
        mock_mode=True,
        oauth_client_id="client",
        oauth_token_endpoint="https://example.com/token",
    )
    app = create_app(settings=settings)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/relay/send",
            json={
                "sender": "alice@example.com",
                "recipient": "bob@example.com",
                "subject": "Hi",
                "body": "Hello",
            },
        )
    assert response.status_code == 200
    data = response.json()
    assert data["accepted"] is True


@pytest.mark.asyncio
async def test_relay_messages_disabled():
    settings = TeaSettings(
        mock_mode=True,
        relay_query_enabled=False,
        oauth_client_id="client",
        oauth_token_endpoint="https://example.com/token",
    )
    app = create_app(settings=settings)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/relay/messages")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_relay_send_requires_auth(monkeypatch):
    settings = TeaSettings(mock_mode=True)
    app = create_app(settings=settings)

    monkeypatch.setattr(
        app.state.container.oauth_client,
        "get_status",
        lambda: OAuthStatus(state=AuthenticationState.UNAUTHENTICATED, message="missing"),
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/relay/send",
            json={
                "sender": "alice@example.com",
                "recipient": "bob@example.com",
                "subject": "Hi",
                "body": "Hello",
            },
        )
    assert response.status_code == 503


@pytest.mark.asyncio
async def test_oauth_refresh_endpoint(monkeypatch):
    settings = TeaSettings(mock_mode=True)
    app = create_app(settings=settings)

    mock_status = OAuthStatus(state=AuthenticationState.AUTHENTICATED, message="refreshed")
    refresh_mock = AsyncMock(return_value=mock_status)
    monkeypatch.setattr(app.state.container.oauth_client, "refresh_access_token", refresh_mock)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/oauth/refresh")

    assert response.status_code == 200
    assert response.json()["state"] == AuthenticationState.AUTHENTICATED
    refresh_mock.assert_awaited_once()
