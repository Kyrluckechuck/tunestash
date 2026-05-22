"""Magic-link email delivery for Queuetip.

SMTP is configured at runtime through the DB-backed app_settings registry
(the in-app Settings page), not Django's static EMAIL_* settings — so an
operator can change it from the UI without a redeploy. When no SMTP host is
configured, mail falls back to the console backend (links print to the
container logs), which is the right default for local dev.
"""

from django.conf import settings
from django.core.mail import EmailMessage, get_connection
from django.core.mail.backends.base import BaseEmailBackend

from src.app_settings.registry import get_setting

_SMTP_BACKEND = "django.core.mail.backends.smtp.EmailBackend"


def magic_link_url(token: str) -> str:
    """Build the public magic-link verification URL for a token."""
    base = getattr(settings, "QUEUETIP_PUBLIC_URL", "http://127.0.0.1:3001").rstrip("/")
    return f"{base}/auth/verify?token={token}"


def _mail_connection() -> BaseEmailBackend:
    """Build a mail connection from app_settings.

    Returns an SMTP connection when `email_host` is configured, otherwise the
    project's default backend (settings.EMAIL_BACKEND) — console in dev/prod so
    links print to the logs, locmem under tests.
    """
    host = (get_setting("email_host") or "").strip()
    if not host:
        return get_connection()
    return get_connection(
        backend=_SMTP_BACKEND,
        host=host,
        port=int(get_setting("email_port")),
        username=get_setting("email_host_user") or "",
        password=get_setting("email_host_password") or "",
        use_tls=bool(get_setting("email_use_tls")),
    )


def send_magic_link_email(email: str, token: str) -> None:
    """Email a one-time sign-in link to the given address."""
    url = magic_link_url(token)
    from_email = (get_setting("email_from") or "").strip() or "queuetip@localhost"
    EmailMessage(
        subject="Your Queuetip sign-in link",
        body=(
            f"Click the link below to sign in to Queuetip:\n\n{url}\n\n"
            "This link expires in 15 minutes. If you did not request it, "
            "you can ignore this email."
        ),
        from_email=from_email,
        to=[email],
        connection=_mail_connection(),
    ).send()
