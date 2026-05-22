"""Shared outbound-mail helpers backed by the DB-stored SMTP settings.

One place builds the mail connection from app_settings, so magic-link sign-in,
the Settings "send test email" button, and operator invites all send the same
way. When no SMTP host is configured, mail falls through to the project default
backend (console in dev/prod → links print to logs; locmem under tests).
"""

from __future__ import annotations

import html
from typing import cast

from django.core.mail import EmailMessage, EmailMultiAlternatives, get_connection
from django.core.mail.backends.base import BaseEmailBackend

from src.app_settings.registry import get_setting

_SMTP_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
_ACCENT = "#2563eb"
_FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"


def build_connection() -> BaseEmailBackend:
    """Mail connection from app_settings; default backend when unconfigured."""
    host = (get_setting("email_host") or "").strip()
    if not host:
        return cast(BaseEmailBackend, get_connection())
    # STARTTLS (587) and implicit SSL (465) are mutually exclusive — Django's
    # SMTP backend raises if both are set. Implicit SSL wins when both are on.
    use_ssl = bool(get_setting("email_use_ssl"))
    use_tls = bool(get_setting("email_use_tls")) and not use_ssl
    return cast(
        BaseEmailBackend,
        get_connection(
            backend=_SMTP_BACKEND,
            host=host,
            port=int(get_setting("email_port")),
            username=get_setting("email_host_user") or "",
            password=get_setting("email_host_password") or "",
            use_tls=use_tls,
            use_ssl=use_ssl,
        ),
    )


def from_address() -> str:
    """The configured From header, or a safe default."""
    return (get_setting("email_from") or "").strip() or "queuetip@localhost"


def render_email(
    *,
    eyebrow: str,
    heading: str,
    paragraphs: list[str],
    button: tuple[str, str] | None = None,
    footer: str | None = None,
) -> str:
    """Render a simple, email-client-safe HTML message.

    Table layout + inline styles (the only thing email clients reliably honor).
    All dynamic text is HTML-escaped. `button` is an optional (label, url) CTA.
    """

    def esc(text: str) -> str:
        return html.escape(text, quote=True)

    body = "".join(
        f'<p style="margin:0 0 16px;font-size:15px;line-height:1.6;color:#334155;">'
        f"{esc(p)}</p>"
        for p in paragraphs
    )
    cta = ""
    if button:
        label, url = button
        cta = (
            '<table role="presentation" cellpadding="0" cellspacing="0" '
            'style="margin:8px 0 8px;"><tr>'
            f'<td style="border-radius:8px;background:{_ACCENT};">'
            f'<a href="{esc(url)}" style="display:inline-block;padding:12px 24px;'
            f"font-family:{_FONT};font-size:15px;font-weight:600;color:#ffffff;"
            f'text-decoration:none;border-radius:8px;">{esc(label)}</a>'
            "</td></tr></table>"
        )
    foot = ""
    if footer:
        foot = (
            '<p style="margin:24px 0 0;font-size:12px;line-height:1.5;'
            f'color:#94a3b8;font-family:{_FONT};">{esc(footer)}</p>'
        )
    return (
        '<!DOCTYPE html><html><body style="margin:0;padding:0;'
        f'background:#f1f5f9;font-family:{_FONT};">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        'style="background:#f1f5f9;padding:24px 12px;"><tr><td align="center">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        'style="max-width:520px;background:#ffffff;border-radius:12px;'
        'border:1px solid #e2e8f0;"><tr>'
        '<td style="padding:28px 32px;">'
        f'<div style="font-size:12px;font-weight:700;letter-spacing:.08em;'
        f"text-transform:uppercase;color:{_ACCENT};margin-bottom:10px;"
        f'font-family:{_FONT};">{esc(eyebrow)}</div>'
        '<h1 style="margin:0 0 16px;font-size:20px;line-height:1.3;color:#0f172a;'
        f'font-weight:700;font-family:{_FONT};">{esc(heading)}</h1>'
        f"{body}{cta}{foot}"
        "</td></tr></table></td></tr></table></body></html>"
    )


def send_message(
    *, subject: str, body: str, to: str, html_body: str | None = None
) -> None:
    """Send a message to a single recipient over the shared connection.

    `body` is the plain-text part; pass `html_body` to also attach an HTML
    alternative (clients pick the richer one, plain-text remains the fallback).
    Raises whatever the backend raises on failure so callers can surface it.
    """
    if html_body:
        msg = EmailMultiAlternatives(
            subject=subject,
            body=body,
            from_email=from_address(),
            to=[to],
            connection=build_connection(),
        )
        msg.attach_alternative(html_body, "text/html")
        msg.send()
        return
    EmailMessage(
        subject=subject,
        body=body,
        from_email=from_address(),
        to=[to],
        connection=build_connection(),
    ).send()
