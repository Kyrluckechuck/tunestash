"""Shared auth flow helpers for magic-link code/password/reset flows."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import string
from datetime import timedelta
from typing import Any, cast

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone

from queuetip.models import (
    Account,
    AuthAttemptLog,
    AuthIdentity,
    LoginCodeChallenge,
    PasswordResetChallenge,
)

from .errors import ValidationError

_LOGIN_CODE_CHARS = string.ascii_uppercase + string.digits
_LOGIN_CODE_LEN = 8
_LOGIN_CODE_MAX_AGE_SECONDS = 15 * 60
_RESET_TOKEN_MAX_AGE_SECONDS = 30 * 60


def _hmac_digest(raw: str) -> str:
    key = settings.SECRET_KEY.encode("utf-8")
    return hmac.new(key, raw.encode("utf-8"), hashlib.sha256).hexdigest()


def _normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def _log_attempt(method: str, identifier: str, ip: str, success: bool) -> None:
    AuthAttemptLog.objects.create(
        method=method,
        identifier=identifier,
        ip_address=ip,
        was_successful=success,
    )


def _is_rate_limited(
    *,
    method: str,
    identifier: str,
    ip: str,
    per_identifier: int,
    per_ip: int,
    window_seconds: int,
) -> bool:
    now = timezone.now()
    since = now - timedelta(seconds=window_seconds)
    ident_count = AuthAttemptLog.objects.filter(
        method=method, identifier=identifier, created_at__gte=since
    ).count()
    if ident_count >= per_identifier:
        return True
    ip_count = AuthAttemptLog.objects.filter(
        method=method, ip_address=ip, created_at__gte=since
    ).count()
    return ip_count >= per_ip


def create_login_code_challenge(account: Account, email: str) -> str:
    """Create a new one-time code challenge for `email` and return raw code."""
    code = "".join(secrets.choice(_LOGIN_CODE_CHARS) for _ in range(_LOGIN_CODE_LEN))
    now = timezone.now()
    LoginCodeChallenge.objects.filter(
        account=account, identifier=email, consumed_at__isnull=True
    ).update(consumed_at=now)
    LoginCodeChallenge.objects.create(
        account=account,
        identifier=email,
        code_hash=_hmac_digest(code),
        expires_at=now + timedelta(seconds=_LOGIN_CODE_MAX_AGE_SECONDS),
    )
    return code


def verify_login_code(email: str, code: str, ip: str) -> Account | None:
    """Verify one-time code and return the account on success."""
    identifier = _normalize_email(email)
    submitted = (code or "").strip().upper()
    if not identifier or not submitted:
        return None
    if _is_rate_limited(
        method=AuthAttemptLog.METHOD_CODE,
        identifier=identifier,
        ip=ip,
        per_identifier=10,
        per_ip=80,
        window_seconds=15 * 60,
    ):
        return None
    now = timezone.now()
    challenge = (
        LoginCodeChallenge.objects.filter(
            identifier=identifier, consumed_at__isnull=True, expires_at__gte=now
        )
        .select_related("account")
        .order_by("-created_at")
        .first()
    )
    if challenge is None:
        _log_attempt(AuthAttemptLog.METHOD_CODE, identifier, ip, False)
        return None
    ok = hmac.compare_digest(challenge.code_hash, _hmac_digest(submitted))
    if not ok:
        _log_attempt(AuthAttemptLog.METHOD_CODE, identifier, ip, False)
        return None
    challenge.consumed_at = now
    challenge.save(update_fields=["consumed_at"])
    _log_attempt(AuthAttemptLog.METHOD_CODE, identifier, ip, True)
    return cast(Account, challenge.account)


def validate_password_strength(
    raw_password: str, *, account: Account | None = None
) -> None:
    try:
        validate_password(raw_password, user=cast(Any, account))
    except DjangoValidationError as exc:
        msg = (
            " ".join(exc.messages)
            if exc.messages
            else "Password does not meet requirements."
        )
        raise ValidationError(msg) from exc


def set_account_password(account: Account, raw_password: str) -> None:
    validate_password_strength(raw_password, account=account)
    account.password_hash = make_password(raw_password)
    account.password_set_at = timezone.now()
    account.save(update_fields=["password_hash", "password_set_at"])


def verify_password_sign_in(email: str, raw_password: str, ip: str) -> Account | None:
    identifier = _normalize_email(email)
    if not identifier or not raw_password:
        return None
    if _is_rate_limited(
        method=AuthAttemptLog.METHOD_PASSWORD,
        identifier=identifier,
        ip=ip,
        per_identifier=12,
        per_ip=120,
        window_seconds=15 * 60,
    ):
        return None
    identity = (
        AuthIdentity.objects.filter(
            provider=AuthIdentity.PROVIDER_MAGIC_LINK, identifier=identifier
        )
        .select_related("account")
        .first()
    )
    if identity is None:
        _log_attempt(AuthAttemptLog.METHOD_PASSWORD, identifier, ip, False)
        return None
    account = cast(Account, identity.account)
    if not account.password_hash or not check_password(
        raw_password, account.password_hash
    ):
        _log_attempt(AuthAttemptLog.METHOD_PASSWORD, identifier, ip, False)
        return None
    _log_attempt(AuthAttemptLog.METHOD_PASSWORD, identifier, ip, True)
    return account


def create_password_reset_challenge(email: str, ip: str) -> str | None:
    """Create password-reset token and return raw token (or None for unknown email)."""
    identifier = _normalize_email(email)
    if not identifier:
        return None
    if _is_rate_limited(
        method=AuthAttemptLog.METHOD_PASSWORD_RESET_REQUEST,
        identifier=identifier,
        ip=ip,
        per_identifier=5,
        per_ip=80,
        window_seconds=60 * 60,
    ):
        return None
    identity = (
        AuthIdentity.objects.filter(
            provider=AuthIdentity.PROVIDER_MAGIC_LINK, identifier=identifier
        )
        .select_related("account")
        .first()
    )
    # Log request regardless to resist account enumeration.
    _log_attempt(AuthAttemptLog.METHOD_PASSWORD_RESET_REQUEST, identifier, ip, True)
    if identity is None:
        return None
    account = cast(Account, identity.account)
    now = timezone.now()
    PasswordResetChallenge.objects.filter(
        account=account, identifier=identifier, consumed_at__isnull=True
    ).update(consumed_at=now)
    raw = secrets.token_urlsafe(32)
    PasswordResetChallenge.objects.create(
        account=account,
        identifier=identifier,
        token_hash=_hmac_digest(raw),
        expires_at=now + timedelta(seconds=_RESET_TOKEN_MAX_AGE_SECONDS),
    )
    return raw


def reset_password_from_token(token: str, new_password: str, ip: str) -> Account | None:
    if not token:
        return None
    token_digest = _hmac_digest(token)
    now = timezone.now()
    challenge = (
        PasswordResetChallenge.objects.filter(
            token_hash=token_digest, consumed_at__isnull=True, expires_at__gte=now
        )
        .select_related("account")
        .first()
    )
    if challenge is None:
        return None
    identifier = challenge.identifier
    if _is_rate_limited(
        method=AuthAttemptLog.METHOD_PASSWORD_RESET_SUBMIT,
        identifier=identifier,
        ip=ip,
        per_identifier=8,
        per_ip=60,
        window_seconds=60 * 60,
    ):
        return None
    try:
        set_account_password(cast(Account, challenge.account), new_password)
    except ValidationError:
        _log_attempt(AuthAttemptLog.METHOD_PASSWORD_RESET_SUBMIT, identifier, ip, False)
        raise
    challenge.consumed_at = now
    challenge.save(update_fields=["consumed_at"])
    _log_attempt(AuthAttemptLog.METHOD_PASSWORD_RESET_SUBMIT, identifier, ip, True)
    return cast(Account, challenge.account)
