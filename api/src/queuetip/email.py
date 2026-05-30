"""Magic-link email delivery for Queuetip.

SMTP is configured at runtime through the DB-backed app_settings registry (the
in-app Settings page) — see src/services/mail.py for the shared connection
builder used by magic links, the Settings test-email button, and invites alike.
"""

from django.conf import settings

from src.services.mail import render_email, send_message


def magic_link_url(token: str) -> str:
    """Build the public magic-link verification URL for a token."""
    base = getattr(settings, "QUEUETIP_PUBLIC_URL", "http://127.0.0.1:3001").rstrip("/")
    return f"{base}/auth/verify?token={token}"


def password_reset_url(token: str) -> str:
    """Build the public reset-password URL for a token."""
    base = getattr(settings, "QUEUETIP_PUBLIC_URL", "http://127.0.0.1:3001").rstrip("/")
    return f"{base}/sign-in?resetToken={token}"


def send_magic_link_email(email: str, token: str, login_code: str) -> None:
    """Email a one-time sign-in link to the given address."""
    url = magic_link_url(token)
    send_message(
        subject="Your Queuetip sign-in link",
        body=(
            f"Click the link below to sign in to Queuetip:\n\n{url}\n\n"
            f"Sign-in code (same 15-minute expiry): {login_code}\n\n"
            "If opening email in a different app/browser, enter that code in your "
            "original browser session.\n\n"
            "This link/code expires in 15 minutes. If you did not request it, "
            "you can ignore this email."
        ),
        to=email,
        html_body=render_email(
            eyebrow="Queuetip",
            heading="Sign in to Queuetip",
            paragraphs=[
                "Click the button below to sign in. This link expires in "
                "15 minutes and can only be used once.",
                f"Raw URL: {url}",
                f"Sign-in code: {login_code}",
                "If your email opens in a different app/browser, enter this code "
                "on the sign-in page in your original browser.",
            ],
            button=("Sign in to Queuetip", url),
            footer="If you didn't request this, you can safely ignore this email.",
        ),
    )


def send_password_reset_email(email: str, token: str) -> None:
    """Email a password-reset link to the given address."""
    url = password_reset_url(token)
    send_message(
        subject="Reset your Queuetip password",
        body=(
            "We received a request to reset your Queuetip password.\n\n"
            f"Reset link:\n{url}\n\n"
            "This link expires in 30 minutes and can only be used once. "
            "If you did not request this, you can ignore this email."
        ),
        to=email,
        html_body=render_email(
            eyebrow="Queuetip",
            heading="Reset your password",
            paragraphs=[
                "Use the button below to reset your password. This link expires in "
                "30 minutes and can only be used once.",
                f"Raw URL: {url}",
            ],
            button=("Reset password", url),
            footer="If you didn't request this, you can safely ignore this email.",
        ),
    )
