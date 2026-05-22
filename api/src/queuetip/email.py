"""Magic-link email delivery for Queuetip."""

from django.conf import settings
from django.core.mail import send_mail


def magic_link_url(token: str) -> str:
    """Build the public magic-link verification URL for a token."""
    base = getattr(settings, "QUEUETIP_PUBLIC_URL", "http://127.0.0.1:3001").rstrip("/")
    return f"{base}/auth/verify?token={token}"


def send_magic_link_email(email: str, token: str) -> None:
    """Email a one-time sign-in link to the given address."""
    url = magic_link_url(token)
    send_mail(
        subject="Your Queuetip sign-in link",
        message=(
            f"Click the link below to sign in to Queuetip:\n\n{url}\n\n"
            "This link expires in 15 minutes. If you did not request it, "
            "you can ignore this email."
        ),
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "queuetip@localhost"),
        recipient_list=[email],
    )
