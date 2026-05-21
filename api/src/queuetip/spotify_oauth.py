"""Spotify OAuth helpers for Queuetip's per-user account linking.

Independent of TuneStash's operator-OAuth at `src.routes.auth` — this flow
links each Queuetip Account to its own Spotify identity. State tokens are
signed via django.core.signing with a 5-minute max-age.

CSRF model mirrors TuneStash's `src.routes.auth`:
  * State token carries the account_id and is signed by the server. An
    attacker cannot forge a state token because they lack the signing key.
    (TuneStash uses an opaque random token + in-memory presence-check; ours
    is signed which is strictly stronger for forgery prevention.)
  * Single-use tracking via `_consume_state` prevents replay within the
    token's 5-minute validity window.

No per-user cookie binding: the user may sign in on origin A (e.g.
http://localhost:3001) but be returned by Spotify to origin B (e.g.
http://127.0.0.1:3001 — required by Spotify), where the session cookie is
not sent. The signed state + single-use guard provide CSRF protection
without requiring same-origin cookies between authorize and callback.
"""

from __future__ import annotations

import threading
import time
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


# Single-use state tracker. Stores `{state_token: issued_at_epoch}`. Entries
# older than STATE_MAX_AGE are reaped on read. In-memory because state tokens
# are short-lived; a process restart just forces users to retry the OAuth
# flow, which is acceptable. Mirrors TuneStash's `_oauth_states` dict.
_used_states: dict[str, float] = {}
_used_states_lock = threading.Lock()


def _consume_state(token: str) -> bool:
    """Record `token` as used. Returns True if it was unused before this call,
    False if it was already consumed (replay). Also reaps expired entries.
    """
    now = time.time()
    with _used_states_lock:
        # Reap expired entries opportunistically.
        cutoff = now - STATE_MAX_AGE
        for k in [k for k, ts in _used_states.items() if ts < cutoff]:
            del _used_states[k]
        if token in _used_states:
            return False
        _used_states[token] = now
        return True


class SpotifyOAuthError(Exception):
    """Raised for OAuth flow failures (bad state, token-exchange failure, etc.)."""


class InvalidStateError(SpotifyOAuthError):
    """State token missing, tampered, expired, or replayed."""


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


def make_state_token(account_id: int) -> str:
    """Sign a state token carrying `account_id`.

    The signature is the CSRF guarantee — an attacker cannot forge a state
    token without the server's SECRET_KEY. The callback must additionally
    call `_consume_state(token)` to prevent replay within the validity window.
    """
    return signing.dumps({"aid": account_id}, salt=_STATE_SALT)


def read_state_token(token: str) -> int:
    """Verify and decode a state token; return the embedded account_id.

    Raises InvalidStateError if the signature is bad, the token has expired,
    or the token has already been consumed (replay). Callers should treat
    any InvalidStateError as a hard rejection of the callback.
    """
    try:
        data = signing.loads(token, salt=_STATE_SALT, max_age=STATE_MAX_AGE)
    except signing.BadSignature as exc:
        raise InvalidStateError(str(exc)) from exc
    if not _consume_state(token):
        raise InvalidStateError("State token already used.")
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
