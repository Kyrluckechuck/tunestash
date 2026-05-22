"""Magic-link email delivery for Queuetip.

SMTP is configured at runtime through the DB-backed app_settings registry (the
in-app Settings page) — see src/services/mail.py for the shared connection
builder used by magic links, the Settings test-email button, and invites alike.
"""

from django.conf import settings

from src.services.mail import send_message


def magic_link_url(token: str) -> str:
    """Build the public magic-link verification URL for a token."""
    base = getattr(settings, "QUEUETIP_PUBLIC_URL", "http://127.0.0.1:3001").rstrip("/")
    return f"{base}/auth/verify?token={token}"


def send_magic_link_email(email: str, token: str) -> None:
    """Email a one-time sign-in link to the given address."""
    url = magic_link_url(token)
    send_message(
        subject="Your Queuetip sign-in link",
        body=(
            f"Click the link below to sign in to Queuetip:\n\n{url}\n\n"
            "This link expires in 15 minutes. If you did not request it, "
            "you can ignore this email."
        ),
        to=email,
    )
