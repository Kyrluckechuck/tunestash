"""Spotify OAuth helpers for Queuetip's per-user account linking.

Independent of TuneStash's operator-OAuth at `src.routes.auth` — this flow
links each Queuetip Account to its own Spotify identity. State tokens are
signed via django.core.signing with a 5-minute max-age.

CSRF model mirrors TuneStash's `src.routes.auth`:
  * State token carries the account_id and is signed by the server. An
    attacker cannot forge a state token because they lack the signing key.
    (TuneStash uses an opaque random token + in-memory presence-check; ours
    is signed which is strictly stronger for forgery prevention.)
  * Database-backed single-use tracking via `_consume_state` prevents replay
    within the token's 5-minute validity window, including after restarts.

No per-user cookie binding: the user may sign in on origin A (e.g.
http://localhost:3001) but be returned by Spotify to origin B (e.g.
http://127.0.0.1:3001 — required by Spotify), where the session cookie is
not sent. The signed state + single-use guard provide CSRF protection
without requiring same-origin cookies between authorize and callback.
"""

from __future__ import annotations

import urllib.parse
from dataclasses import dataclass
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


def _consume_state(token: str) -> bool:
    """Record `token` as used. Returns True if it was unused before this call,
    False if it was already consumed (replay). Also reaps expired entries.
    """
    from src.queuetip.replay import consume_token

    return consume_token("spotify_oauth_state", token, STATE_MAX_AGE)


class SpotifyOAuthError(Exception):
    """Raised for OAuth flow failures (bad state, token-exchange failure, etc.)."""


class SpotifyTokenRefreshError(SpotifyOAuthError):
    """Raised when Spotify rejects a refresh-token request."""

    def __init__(self, status_code: int, body: str) -> None:
        self.status_code = status_code
        self.body = body
        super().__init__(f"Spotify token refresh failed: {status_code} {body}")


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


@dataclass(frozen=True)
class StatePayload:
    """Decoded Spotify OAuth state token."""

    account_id: int
    # Browser-facing origin the user was on when they clicked Connect Spotify.
    # The callback uses this for the post-OAuth redirect so the user lands
    # back where they started instead of being teleported to 127.0.0.1
    # (which is where the redirect_uri itself must point per Spotify's rules).
    return_origin: str | None = None


def make_state_token(account_id: int, return_origin: str | None = None) -> str:
    """Sign a state token carrying `account_id` and an optional return origin.

    The signature is the CSRF guarantee — an attacker cannot forge a state
    token without the server's SECRET_KEY. The callback must additionally
    call `_consume_state(token)` to prevent replay within the validity window.

    `return_origin` is the scheme://host[:port] the user's browser was on
    when they initiated the OAuth flow. It's signed in (not just appended)
    so a forwarded link can't be tampered with to swap in an attacker host.
    """
    payload: dict[str, Any] = {"aid": account_id}
    if return_origin:
        payload["ro"] = return_origin
    return signing.dumps(payload, salt=_STATE_SALT)


def read_state_token(token: str) -> StatePayload:
    """Verify and decode a state token; return the embedded payload.

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
    return StatePayload(
        account_id=int(data["aid"]),
        return_origin=data.get("ro") or None,
    )


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
        raise SpotifyTokenRefreshError(response.status_code, response.text)
    return dict(response.json())


def is_hard_refresh_error(exc: Exception) -> bool:
    """True when Spotify says the stored refresh token cannot be reused."""
    if isinstance(exc, SpotifyTokenRefreshError):
        return exc.status_code in (400, 401)
    message = str(exc).lower()
    return "invalid_grant" in message or " 400 " in message or " 401 " in message


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
