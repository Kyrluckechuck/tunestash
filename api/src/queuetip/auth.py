"""Magic-link and session tokens for Queuetip, built on django.core.signing.

Using Django's own signing framework (vetted, maintained) instead of
django-sesame, which is coupled to AUTH_USER_MODEL — Queuetip's Account is a
standalone model, not the project user model.
"""

import hashlib
import threading
import time
from dataclasses import dataclass

from django.core import signing

# Cookie carrying the session token on the public process.
SESSION_COOKIE = "queuetip_session"

_MAGIC_SALT = "queuetip.magic-link"
_SESSION_SALT = "queuetip.session"

MAGIC_LINK_MAX_AGE = 15 * 60  # 15 minutes
SESSION_MAX_AGE = 30 * 24 * 60 * 60  # 30 days


class InvalidTokenError(Exception):
    """Raised when a token is malformed, tampered with, or expired."""


@dataclass(frozen=True)
class SessionPayload:
    """Decoded session token payload."""

    account_id: int
    session_epoch: int


def make_magic_link_token(account_id: int) -> str:
    """Sign a short-lived token identifying an account for magic-link login."""
    return signing.dumps({"aid": account_id}, salt=_MAGIC_SALT)


# Single-use guard for magic-link tokens. Stores {token_digest: consumed_epoch};
# entries older than the token lifetime are reaped on read. In-memory, mirroring
# the OAuth state guard (spotify_oauth._used_states): a process restart drops the
# set, which only re-opens the already narrow (signature + 15-min-expiry-bound)
# replay window. A DB-backed nonce would close that residual gap fully.
_consumed_magic: dict[str, float] = {}
_consumed_magic_lock = threading.Lock()


def _consume_magic_token(token: str) -> bool:
    """Record `token` as used. Returns True if it was unused before this call,
    False if it was already consumed (replay)."""
    digest = hashlib.sha256(token.encode()).hexdigest()
    now = time.time()
    with _consumed_magic_lock:
        cutoff = now - MAGIC_LINK_MAX_AGE
        for k in [k for k, ts in _consumed_magic.items() if ts < cutoff]:
            del _consumed_magic[k]
        if digest in _consumed_magic:
            return False
        _consumed_magic[digest] = now
        return True


def read_magic_link_token(token: str) -> int:
    """Return the account id from a magic-link token, or raise InvalidTokenError.

    Single-use: a token that has already been redeemed (or is malformed,
    tampered, or expired) raises InvalidTokenError. This prevents replay of a
    link intercepted from email relays, proxy log prefetch, or shared history.
    """
    try:
        data = signing.loads(token, salt=_MAGIC_SALT, max_age=MAGIC_LINK_MAX_AGE)
    except signing.BadSignature as exc:
        raise InvalidTokenError(str(exc)) from exc
    if not _consume_magic_token(token):
        raise InvalidTokenError("Magic link has already been used.")
    return int(data["aid"])


def make_session_token(account_id: int, session_epoch: int = 0) -> str:
    """Sign a long-lived session token embedding the account id and epoch.

    The epoch allows all existing sessions to be invalidated atomically by
    bumping Account.session_epoch (see signOutEverywhere mutation).
    """
    return signing.dumps({"aid": account_id, "ep": session_epoch}, salt=_SESSION_SALT)


def read_session_token(token: str) -> SessionPayload:
    """Return the decoded session payload, or raise InvalidTokenError.

    Legacy tokens (without the ``ep`` field, issued before session epoch was
    added) are treated as epoch 0 for backward compatibility. As long as the
    account's session_epoch is still 0, they continue to work.
    """
    try:
        data = signing.loads(token, salt=_SESSION_SALT, max_age=SESSION_MAX_AGE)
    except signing.BadSignature as exc:
        raise InvalidTokenError(str(exc)) from exc
    return SessionPayload(
        account_id=int(data["aid"]),
        session_epoch=int(data.get("ep", 0)),
    )
