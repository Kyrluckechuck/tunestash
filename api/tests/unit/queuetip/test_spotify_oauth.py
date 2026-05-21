"""Unit tests for the Queuetip Spotify OAuth state-signing helpers."""

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from asgiref.sync import sync_to_async

from src.queuetip import routes as queuetip_routes
from src.queuetip import spotify_oauth

_NONCE_A = spotify_oauth._derive_nonce("session-token-A")
_NONCE_B = spotify_oauth._derive_nonce("session-token-B")


def test_state_round_trip():
    token = spotify_oauth.make_state_token(42, session_nonce=_NONCE_A)
    assert spotify_oauth.read_state_token(token, expected_nonce=_NONCE_A) == 42


def test_tampered_state_rejected():
    token = spotify_oauth.make_state_token(1, session_nonce=_NONCE_A)
    with pytest.raises(spotify_oauth.InvalidStateError):
        spotify_oauth.read_state_token(token + "x", expected_nonce=_NONCE_A)


def test_expired_state_rejected():
    token = spotify_oauth.make_state_token(1, session_nonce=_NONCE_A)
    with patch.object(spotify_oauth, "STATE_MAX_AGE", -1):
        with pytest.raises(spotify_oauth.InvalidStateError):
            spotify_oauth.read_state_token(token, expected_nonce=_NONCE_A)


def test_wrong_session_nonce_rejected():
    """A state token issued for session A must be rejected when verified against session B."""
    token = spotify_oauth.make_state_token(99, session_nonce=_NONCE_A)
    with pytest.raises(spotify_oauth.InvalidStateError, match="nonce"):
        spotify_oauth.read_state_token(token, expected_nonce=_NONCE_B)


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
    """If only Host is present (no proxy), use it."""
    req = _fake_request(headers={"Host": "queuetip.example.com"})
    assert (
        queuetip_routes._queuetip_callback_uri(req)
        == "http://queuetip.example.com/auth/spotify/callback"
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
