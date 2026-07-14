"""Database-backed replay protection for short-lived authentication tokens."""

from __future__ import annotations

import hashlib
from datetime import timedelta

from django.db import IntegrityError
from django.utils import timezone

from queuetip.models import AuthReplayGuard


def consume_token(kind: str, token: str, max_age: int) -> bool:
    """Atomically consume a token, returning false for a replay."""
    now = timezone.now()
    AuthReplayGuard.objects.filter(expires_at__lt=now).delete()
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    try:
        AuthReplayGuard.objects.create(
            kind=kind,
            token_digest=digest,
            expires_at=now + timedelta(seconds=max_age),
        )
    except IntegrityError:
        return False
    return True
