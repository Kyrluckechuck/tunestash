"""Integration tests for the Queuetip Spotify OAuth start/callback routes."""

from unittest.mock import patch

import httpx
import pytest
from asgiref.sync import sync_to_async

from queuetip.models import Account, ExternalServiceLink
from src.queuetip import spotify_oauth
from src.queuetip.app import app
from src.queuetip.auth import SESSION_COOKIE, make_session_token


def _authed_client(account_id: int) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    client = httpx.AsyncClient(transport=transport, base_url="http://testserver")
    client.cookies.set(SESSION_COOKIE, make_session_token(account_id))
    return client


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_start_requires_session():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        response = await client.get("/auth/spotify/start")
    assert response.status_code == 401


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_start_invalid_session_returns_401():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        client.cookies.set(SESSION_COOKIE, "not.a.valid.token")
        response = await client.get("/auth/spotify/start")
    assert response.status_code == 401


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_start_redirects_to_spotify():
    account = await sync_to_async(Account.objects.create)(display_name="Jo")
    with patch.object(spotify_oauth, "get_credentials", return_value=("cid", "sec")):
        async with _authed_client(account.id) as client:
            response = await client.get("/auth/spotify/start", follow_redirects=False)
    assert response.status_code == 302
    location = response.headers["location"]
    assert location.startswith("https://accounts.spotify.com/authorize")
    assert "state=" in location


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_start_503_when_spotify_not_configured():
    account = await sync_to_async(Account.objects.create)(display_name="Jo")
    with patch.object(
        spotify_oauth,
        "get_credentials",
        side_effect=spotify_oauth.SpotifyOAuthError("not configured"),
    ):
        async with _authed_client(account.id) as client:
            response = await client.get("/auth/spotify/start", follow_redirects=False)
    assert response.status_code == 503


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_callback_upserts_external_service_link():
    account = await sync_to_async(Account.objects.create)(display_name="Jo")
    state = spotify_oauth.make_state_token(account.id)
    tokens = {
        "access_token": "AT",
        "refresh_token": "RT",
        "expires_in": 3600,
        "scope": "playlist-modify-private playlist-modify-public",
    }
    with (
        patch("src.queuetip.routes.exchange_code_for_tokens", return_value=tokens),
        patch(
            "src.queuetip.routes.get_spotify_user_id", return_value="spotify_user_42"
        ),
    ):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            response = await client.get(
                "/auth/spotify/callback",
                params={"code": "CODE", "state": state},
                follow_redirects=False,
            )
    assert response.status_code == 302
    assert "spotify_linked=1" in response.headers["location"]

    link = await sync_to_async(ExternalServiceLink.objects.get)(
        account=account, service="spotify"
    )
    assert link.access_token == "AT"
    assert link.refresh_token == "RT"
    assert link.service_user_id == "spotify_user_42"
    assert link.scope == "playlist-modify-private playlist-modify-public"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_callback_updates_existing_link():
    """update_or_create replaces an existing ExternalServiceLink."""
    account = await sync_to_async(Account.objects.create)(display_name="Jo")
    from datetime import datetime
    from datetime import timezone as tz

    await sync_to_async(ExternalServiceLink.objects.create)(
        account=account,
        service="spotify",
        access_token="OLD_AT",
        refresh_token="OLD_RT",
        expires_at=datetime(2020, 1, 1, tzinfo=tz.utc),
        scope="",
        service_user_id="old_user",
    )

    state = spotify_oauth.make_state_token(account.id)
    tokens = {
        "access_token": "NEW_AT",
        "refresh_token": "NEW_RT",
        "expires_in": 3600,
        "scope": "playlist-modify-private",
    }
    with (
        patch("src.queuetip.routes.exchange_code_for_tokens", return_value=tokens),
        patch("src.queuetip.routes.get_spotify_user_id", return_value="new_user"),
    ):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            response = await client.get(
                "/auth/spotify/callback",
                params={"code": "CODE2", "state": state},
                follow_redirects=False,
            )
    assert response.status_code == 302

    count = await sync_to_async(
        ExternalServiceLink.objects.filter(account=account, service="spotify").count
    )()
    assert count == 1
    link = await sync_to_async(ExternalServiceLink.objects.get)(
        account=account, service="spotify"
    )
    assert link.access_token == "NEW_AT"
    assert link.service_user_id == "new_user"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_callback_missing_code_returns_400():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        response = await client.get("/auth/spotify/callback")
    assert response.status_code == 400


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_callback_tampered_state_returns_400():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        response = await client.get(
            "/auth/spotify/callback",
            params={"code": "CODE", "state": "tampered.state.token"},
            follow_redirects=False,
        )
    assert response.status_code == 400


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_callback_spotify_error_param_returns_400():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        response = await client.get(
            "/auth/spotify/callback",
            params={"error": "access_denied"},
            follow_redirects=False,
        )
    assert response.status_code == 400
