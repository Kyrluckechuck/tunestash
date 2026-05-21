"""Spotify OAuth helpers for Queuetip's per-user account linking.

Independent of TuneStash's operator-OAuth at `src.routes.auth` — this flow
links each Queuetip Account to its own Spotify identity. State tokens are
signed via django.core.signing with a 5-minute max-age.

State tokens include a session nonce (first 16 hex chars of SHA-256 of the
session cookie value) so a token issued for one session cannot be replayed
from a different session (CSRF binding).
"""

from __future__ import annotations

import hashlib
import urllib.parse
from typing import Any

from django.core import signing

import httpx

from src.app_settings.registry import get_setting

OAUTH_AUTHORIZE_URL = "https://accounts.spotify.com/authorize"
OAUTH_TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_API_BASE = "https://api.spotify.com/v1"

OAUTH_SCOPES = ["playlist-modify-private", "playlist-modify-public"]
_STATE_SALT = "queuetip.spotify.oauth-state"
STATE_MAX_AGE = 300  # 5 minutes


def _derive_nonce(session_token: str) -> str:
    """Derive a short, stable nonce from a session token.

    Uses the first 16 hex characters (64 bits) of SHA-256.  Short enough to
    keep the state token compact; long enough to make cross-session replay
    computationally infeasible.
    """
    return hashlib.sha256(session_token.encode()).hexdigest()[:16]


class SpotifyOAuthError(Exception):
    """Raised for OAuth flow failures (bad state, token-exchange failure, etc.)."""


class InvalidStateError(SpotifyOAuthError):
    """State token missing, tampered, or expired."""


def get_credentials() -> tuple[str, str]:
    """Read the Spotify Dev App client id + secret from TuneStash settings."""
    try:
        client_id = get_setting("spotipy_client_id") or ""
        client_secret = get_setting("spotipy_client_secret") or ""
    except Exception as exc:
        raise SpotifyOAuthError(
            "Spotify is not configured. Set spotipy_client_id and "
            "spotipy_client_secret in TuneStash settings."
        ) from exc
    if not client_id or not client_secret:
        raise SpotifyOAuthError(
            "Spotify is not configured. Set spotipy_client_id and "
            "spotipy_client_secret in TuneStash settings."
        )
    return client_id, client_secret


def make_state_token(account_id: int, session_nonce: str) -> str:
    """Sign a state token binding `account_id` to the caller's session nonce.

    The nonce must be derived from the current session cookie via
    `_derive_nonce()` before calling this function.
    """
    return signing.dumps({"aid": account_id, "nonce": session_nonce}, salt=_STATE_SALT)


def read_state_token(token: str, expected_nonce: str) -> int:
    """Verify and decode a state token; raises InvalidStateError on any mismatch.

    Verifies signature, expiry (STATE_MAX_AGE), and that the embedded nonce
    matches `expected_nonce` (i.e. the nonce derived from the callback caller's
    session cookie).  A mismatch means the callback came from a different
    session than the one that initiated the flow.
    """
    try:
        data = signing.loads(token, salt=_STATE_SALT, max_age=STATE_MAX_AGE)
    except signing.BadSignature as exc:
        raise InvalidStateError(str(exc)) from exc
    if data.get("nonce") != expected_nonce:
        raise InvalidStateError("Session nonce mismatch — possible CSRF.")
    return int(data["aid"])


def build_authorize_url(state: str, redirect_uri: str) -> str:
    client_id, _ = get_credentials()
    params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": " ".join(OAUTH_SCOPES),
        "state": state,
    }
    return f"{OAUTH_AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"


def exchange_code_for_tokens(code: str, redirect_uri: str) -> dict[str, Any]:
    client_id, client_secret = get_credentials()
    response = httpx.post(
        OAUTH_TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
        },
        auth=(client_id, client_secret),
        timeout=10.0,
    )
    if response.status_code != 200:
        raise SpotifyOAuthError(
            f"Spotify token exchange failed: {response.status_code} {response.text}"
        )
    return dict(response.json())


def refresh_access_token(refresh_token: str) -> dict[str, Any]:
    client_id, client_secret = get_credentials()
    response = httpx.post(
        OAUTH_TOKEN_URL,
        data={"grant_type": "refresh_token", "refresh_token": refresh_token},
        auth=(client_id, client_secret),
        timeout=10.0,
    )
    if response.status_code != 200:
        raise SpotifyOAuthError(
            f"Spotify token refresh failed: {response.status_code} {response.text}"
        )
    return dict(response.json())


def get_spotify_user_id(access_token: str) -> str:
    response = httpx.get(
        f"{SPOTIFY_API_BASE}/me",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=10.0,
    )
    if response.status_code != 200:
        raise SpotifyOAuthError(
            f"Spotify /me failed: {response.status_code} {response.text}"
        )
    return str(response.json()["id"])
