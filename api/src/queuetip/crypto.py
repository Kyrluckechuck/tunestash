"""Symmetric encryption helpers for Queuetip-owned secrets.

Used today for SubsonicConnection.password_encrypted; reserved for any other
at-rest secret we add to the queuetip app. Keep this module narrow — it
exists so secret-handling code lives in exactly one place, not because the
project needs a crypto layer in general.

Key sourcing:
  * Reads QUEUETIP_FERNET_KEY from Django settings (set in api/settings.py
    from the same-named env var; falls back to a derived dev key in DEBUG).
  * In production set this to a real, persisted Fernet key (`Fernet.generate_key()`).
    Rotation: use MultiFernet with both old and new keys, re-encrypt on next
    write — out of scope here, callers can do it themselves when needed.

Why this is its own module rather than inline in models.py: encrypting in a
model save() couples the persistence layer to a settings lookup, which makes
unit-testing models painful. Keeping it as a free function lets callers
decide when to encrypt (typically at the service layer) and lets tests mock
the helpers without touching Django settings.
"""

from __future__ import annotations

import base64
import hashlib
import logging

from django.conf import settings

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)


class CryptoError(Exception):
    """Raised when encryption or decryption fails."""


def _get_fernet() -> Fernet:
    """Build a Fernet instance from settings.QUEUETIP_FERNET_KEY.

    In DEBUG with no key set, derives a dev key from SECRET_KEY. NEVER use
    that path in production — secret rotation would change the derived key
    and silently invalidate all stored ciphertexts.
    """
    key = getattr(settings, "QUEUETIP_FERNET_KEY", "") or ""
    if not key:
        if not getattr(settings, "DEBUG", False):
            raise CryptoError(
                "QUEUETIP_FERNET_KEY is not configured. Generate one via "
                "`python -c 'from cryptography.fernet import Fernet; "
                "print(Fernet.generate_key().decode())'` and set it in your "
                "environment."
            )
        # Dev-only fallback: derive deterministically from SECRET_KEY so the
        # same dev DB keeps working across restarts.
        digest = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
        key = base64.urlsafe_b64encode(digest).decode()
        logger.warning(
            "QUEUETIP_FERNET_KEY not set — using SECRET_KEY-derived dev key. "
            "Do not use in production."
        )
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_secret(plaintext: str) -> bytes:
    """Encrypt a UTF-8 string and return the Fernet ciphertext."""
    if not isinstance(plaintext, str):
        raise CryptoError("encrypt_secret expects a str")
    return _get_fernet().encrypt(plaintext.encode("utf-8"))


def decrypt_secret(ciphertext: bytes | memoryview) -> str:
    """Decrypt a Fernet ciphertext back to its original UTF-8 string."""
    if isinstance(ciphertext, memoryview):
        ciphertext = bytes(ciphertext)
    try:
        return _get_fernet().decrypt(ciphertext).decode("utf-8")
    except InvalidToken as exc:
        raise CryptoError(
            "Decryption failed — wrong key, tampered data, or stale ciphertext."
        ) from exc
