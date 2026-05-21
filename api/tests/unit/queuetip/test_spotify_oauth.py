"""Unit tests for the Queuetip Spotify OAuth state-signing helpers."""

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from asgiref.sync import sync_to_async

from src.queuetip import routes as queuetip_routes
from src.queuetip import spotify_oauth


@pytest.fixture(autouse=True)
def _clear_used_states():
    """Wipe the single-use state tracker between tests so they don't see
    each other's tokens as 'already consumed'."""
    spotify_oauth._used_states.clear()
    yield
    spotify_oauth._used_states.clear()


def test_state_round_trip():
    token = spotify_oauth.make_state_token(42)
    assert spotify_oauth.read_state_token(token) == 42


def test_tampered_state_rejected():
    token = spotify_oauth.make_state_token(1)
    with pytest.raises(spotify_oauth.InvalidStateError):
        spotify_oauth.read_state_token(token + "x")


def test_expired_state_rejected():
    token = spotify_oauth.make_state_token(1)
    with patch.object(spotify_oauth, "STATE_MAX_AGE", -1):
        with pytest.raises(spotify_oauth.InvalidStateError):
            spotify_oauth.read_state_token(token)


def test_state_token_is_single_use():
    """Replay protection: a state token consumed once must be rejected if
    presented again (matches TuneStash's `del _oauth_states[state]` pattern)."""
    token = spotify_oauth.make_state_token(7)
    assert spotify_oauth.read_state_token(token) == 7
    with pytest.raises(spotify_oauth.InvalidStateError, match="already used"):
        spotify_oauth.read_state_token(token)


def test_build_authorize_url_includes_state_and_scope():
    with patch.object(spotify_oauth, "get_credentials", return_value=("cid", "sec")):
        url = spotify_oauth.build_authorize_url(
            state="abc", redirect_uri="http://localhost:5050/auth/spotify/callback"
        )
    assert "state=abc" in url
    assert "client_id=cid" in url
    assert "scope=playlist-modify-private+playlist-modify-public" in url


def test_build_authorize_url_points_to_spotify():
    with patch.object(spotify_oauth, "get_credentials", return_value=("cid", "sec")):
        url = spotify_oauth.build_authorize_url(
            state="tok", redirect_uri="http://localhost:5050/auth/spotify/callback"
        )
    assert url.startswith("https://accounts.spotify.com/authorize")


def test_get_credentials_raises_when_missing():
    with patch.object(
        spotify_oauth,
        "get_setting",
        side_effect=lambda k: "",
    ):
        with pytest.raises(spotify_oauth.SpotifyOAuthError, match="not configured"):
            spotify_oauth.get_credentials()


def test_build_authorize_url_works_via_sync_to_async():
    """Regression: the /auth/spotify/start route is async and must invoke
    build_authorize_url through sync_to_async. get_setting() reads from the DB,
    which raises SynchronousOnlyOperation in an async event loop. The registry
    silently swallows that exception and returns the default ("") — making the
    failure look like a false "Spotify is not configured" 503 to the user.

    Pin the contract: when wrapped in sync_to_async, build_authorize_url must
    successfully read credentials and produce a valid Spotify authorize URL.
    """

    async def call_from_async() -> str:
        with patch.object(
            spotify_oauth, "get_credentials", return_value=("real-id", "real-secret")
        ):
            return await sync_to_async(spotify_oauth.build_authorize_url)(
                state="s", redirect_uri="http://localhost:5050/auth/spotify/callback"
            )

    url = asyncio.run(call_from_async())
    assert "client_id=real-id" in url
    assert url.startswith("https://accounts.spotify.com/authorize")


def _fake_request(headers=None, scheme="http"):
    """Build a minimal Request stand-in for `_queuetip_callback_uri`."""
    return SimpleNamespace(
        headers={k.lower(): v for k, v in (headers or {}).items()},
        url=SimpleNamespace(scheme=scheme),
    )


def test_callback_uri_prefers_x_forwarded_host():
    """When the Vite proxy / nginx sets X-Forwarded-Host, the callback URI
    must reflect the browser-facing host so it matches Spotify's allowlist."""
    req = _fake_request(
        headers={"X-Forwarded-Host": "127.0.0.1:3001", "Host": "queuetip:5000"}
    )
    assert (
        queuetip_routes._queuetip_callback_uri(req)
        == "http://127.0.0.1:3001/auth/spotify/callback"
    )


def test_callback_uri_falls_back_to_host_header():
    """If only Host is present (no proxy), use it. Non-loopback hosts get
    https forced — covered separately by the forces_https test."""
    req = _fake_request(headers={"Host": "127.0.0.1:3001"})
    assert (
        queuetip_routes._queuetip_callback_uri(req)
        == "http://127.0.0.1:3001/auth/spotify/callback"
    )


def test_callback_uri_respects_x_forwarded_proto():
    """HTTPS termination at the proxy should produce an https:// redirect URI."""
    req = _fake_request(
        headers={
            "X-Forwarded-Host": "queuetip.example.com",
            "X-Forwarded-Proto": "https",
        }
    )
    assert (
        queuetip_routes._queuetip_callback_uri(req)
        == "https://queuetip.example.com/auth/spotify/callback"
    )


def test_callback_uri_rewrites_localhost_to_loopback_ip():
    """Spotify rejects 'localhost' for loopback URIs — swap to 127.0.0.1.
    Mirrors api/src/routes/auth.py:37."""
    req = _fake_request(headers={"X-Forwarded-Host": "localhost:3001"})
    assert (
        queuetip_routes._queuetip_callback_uri(req)
        == "http://127.0.0.1:3001/auth/spotify/callback"
    )


def test_callback_uri_forces_https_for_non_loopback_hosts():
    """Public deployments must use HTTPS for Spotify OAuth — even if the proxy
    forwarded plain HTTP, force https on non-loopback hosts."""
    req = _fake_request(
        headers={"X-Forwarded-Host": "queuetip.example.com"},
        scheme="http",
    )
    assert (
        queuetip_routes._queuetip_callback_uri(req)
        == "https://queuetip.example.com/auth/spotify/callback"
    )


def test_callback_uri_falls_back_to_setting_when_no_request():
    """Background callers without a request (tests, tasks) use QUEUETIP_PUBLIC_URL."""
    with patch.object(
        queuetip_routes,
        "settings",
        SimpleNamespace(QUEUETIP_PUBLIC_URL="https://prod.example.com/"),
    ):
        assert (
            queuetip_routes._queuetip_callback_uri(None)
            == "https://prod.example.com/auth/spotify/callback"
        )
