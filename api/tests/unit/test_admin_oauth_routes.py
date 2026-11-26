# pylint: disable=protected-access

"""Regression tests for the TuneStash operator Spotify OAuth routes.

Covers reflected-XSS hardening, bounded/expiring single-use state, and use of
the configured redirect URI instead of untrusted proxy headers.
"""

import time
from unittest.mock import patch

import httpx
import pytest
from fastapi import FastAPI

from src.routes import auth as admin_auth


def _client() -> httpx.AsyncClient:
    app = FastAPI()
    app.include_router(admin_auth.router)
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    )


def _reset_states() -> None:
    with admin_auth._states_lock:
        admin_auth._oauth_states.clear()


# ---------------------------------------------------------------------------
# #1 — reflected XSS in error pages
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_callback_error_escapes_html():
    payload = "<script>alert(1)</script>"
    async with _client() as client:
        response = await client.get("/auth/spotify/callback", params={"error": payload})

    assert response.status_code == 400
    assert "<script>alert(1)</script>" not in response.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in response.text


@pytest.mark.asyncio
async def test_callback_error_page_has_restrictive_csp():
    async with _client() as client:
        response = await client.get(
            "/auth/spotify/callback", params={"error": "access_denied"}
        )

    csp = response.headers.get("content-security-policy", "")
    assert "script-src 'none'" in csp
    assert "default-src 'none'" in csp


@pytest.mark.asyncio
async def test_callback_exception_does_not_leak_raw_text():
    _reset_states()
    state = "state-exc"
    admin_auth._store_state(state, "http://127.0.0.1:5000/auth/spotify/callback")

    secret = "SECRET_UPSTREAM_BODY_<script>alert(1)</script>"
    with patch.object(
        admin_auth.SpotifyOAuthService,
        "exchange_code_for_tokens",
        side_effect=RuntimeError(secret),
    ):
        async with _client() as client:
            response = await client.get(
                "/auth/spotify/callback",
                params={"code": "abc", "state": state},
            )

    assert response.status_code == 500
    assert secret not in response.text
    assert "<script>" not in response.text


# ---------------------------------------------------------------------------
# #6 — bounded, expiring, single-use state
# ---------------------------------------------------------------------------


def test_state_store_is_bounded():
    _reset_states()
    for index in range(admin_auth._OAUTH_STATE_MAX + 50):
        admin_auth._store_state(f"state-{index}", "http://127.0.0.1:5000/callback")

    with admin_auth._states_lock:
        assert len(admin_auth._oauth_states) <= admin_auth._OAUTH_STATE_MAX


def test_state_store_expires_old_entries(monkeypatch):
    _reset_states()
    now = time.monotonic()
    monkeypatch.setattr(admin_auth.time, "monotonic", lambda: now)
    admin_auth._store_state("old", "http://127.0.0.1:5000/callback")

    monkeypatch.setattr(
        admin_auth.time,
        "monotonic",
        lambda: now + admin_auth._OAUTH_STATE_TTL + 1,
    )
    assert admin_auth._consume_state("old", "http://127.0.0.1:5000/callback") is False


def test_state_is_single_use():
    _reset_states()
    uri = "http://127.0.0.1:5000/auth/spotify/callback"
    admin_auth._store_state("once", uri)

    assert admin_auth._consume_state("once", uri) is True
    assert admin_auth._consume_state("once", uri) is False


def test_state_is_bound_to_redirect_uri():
    _reset_states()
    admin_auth._store_state("bound", "http://127.0.0.1:5000/auth/spotify/callback")

    assert (
        admin_auth._consume_state(
            "bound", "http://127.0.0.1:5000/auth/spotify/callback"
        )
        is True
    )
    _reset_states()
    admin_auth._store_state("bound2", "http://127.0.0.1:5000/auth/spotify/callback")
    assert admin_auth._consume_state("bound2", "https://evil.example/callback") is False


# ---------------------------------------------------------------------------
# #7 (OAuth) — canonical redirect URI, never from forwarded headers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_authorize_uses_configured_redirect_uri_and_sets_state():
    _reset_states()
    configured = "http://127.0.0.1:5000/auth/spotify/callback"

    with (
        patch.object(
            admin_auth.SpotifyOAuthService,
            "get_authorization_url",
            return_value=("https://accounts.spotify.com/authorize?state=s", "s"),
        ) as get_url,
        patch.object(admin_auth, "_configured_redirect_uri", return_value=configured),
    ):
        async with _client() as client:
            response = await client.get(
                "/auth/spotify/authorize",
                headers={
                    "x-forwarded-host": "evil.example",
                    "x-forwarded-proto": "https",
                },
                follow_redirects=False,
            )

    assert response.status_code == 302
    get_url.assert_called_once_with(redirect_uri=configured)
    with admin_auth._states_lock:
        assert "s" in admin_auth._oauth_states


@pytest.mark.asyncio
async def test_callback_exchanges_with_configured_redirect_uri():
    _reset_states()
    configured = "http://127.0.0.1:5000/auth/spotify/callback"
    admin_auth._store_state("exchange", configured)

    with (
        patch.object(admin_auth, "_configured_redirect_uri", return_value=configured),
        patch.object(
            admin_auth.SpotifyOAuthService,
            "exchange_code_for_tokens",
            return_value={"access_token": "AT"},
        ) as exchange,
        patch.object(admin_auth.SpotifyOAuthService, "save_tokens") as save,
    ):
        async with _client() as client:
            response = await client.get(
                "/auth/spotify/callback",
                params={"code": "c", "state": "exchange"},
                headers={"x-forwarded-host": "evil.example"},
            )

    assert response.status_code == 200
    exchange.assert_called_once_with("c", configured)
    save.assert_called_once_with({"access_token": "AT"})


def test_configured_redirect_uri_falls_back_to_safe_default():
    with patch.object(admin_auth, "get_setting_with_default", return_value=None):
        uri = admin_auth._configured_redirect_uri()
    assert uri == "http://127.0.0.1:5000/auth/spotify/callback"
