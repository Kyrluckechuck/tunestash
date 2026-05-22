"""Shared outbound-mail helpers backed by the DB-stored SMTP settings.

One place builds the mail connection from app_settings, so magic-link sign-in,
the Settings "send test email" button, and operator invites all send the same
way. When no SMTP host is configured, mail falls through to the project default
backend (console in dev/prod → links print to logs; locmem under tests).
"""

from __future__ import annotations

from typing import cast

from django.core.mail import EmailMessage, get_connection
from django.core.mail.backends.base import BaseEmailBackend

from src.app_settings.registry import get_setting

_SMTP_BACKEND = "django.core.mail.backends.smtp.EmailBackend"


def build_connection() -> BaseEmailBackend:
    """Mail connection from app_settings; default backend when unconfigured."""
    host = (get_setting("email_host") or "").strip()
    if not host:
        return cast(BaseEmailBackend, get_connection())
    return cast(
        BaseEmailBackend,
        get_connection(
            backend=_SMTP_BACKEND,
            host=host,
            port=int(get_setting("email_port")),
            username=get_setting("email_host_user") or "",
            password=get_setting("email_host_password") or "",
            use_tls=bool(get_setting("email_use_tls")),
        ),
    )


def from_address() -> str:
    """The configured From header, or a safe default."""
    return (get_setting("email_from") or "").strip() or "queuetip@localhost"


def send_message(*, subject: str, body: str, to: str) -> None:
    """Send a plain-text message to a single recipient over the shared connection.

    Raises whatever the backend raises on failure (SMTP/auth/connection errors)
    so callers can surface a useful message to the operator.
    """
    EmailMessage(
        subject=subject,
        body=body,
        from_email=from_address(),
        to=[to],
        connection=build_connection(),
    ).send()
