from django.core.mail.backends.smtp import EmailBackend as SmtpBackend

import pytest

from library_manager.models import AppSetting
from src.queuetip.email import _mail_connection, magic_link_url, send_magic_link_email


def test_magic_link_url_includes_token():
    url = magic_link_url("abc123")
    assert url.endswith("/auth/verify?token=abc123")
    assert "://" in url


@pytest.mark.django_db
def test_send_magic_link_email_delivers_with_link(mailoutbox):
    send_magic_link_email("friend@example.com", "tok456")
    assert len(mailoutbox) == 1
    message = mailoutbox[0]
    assert message.to == ["friend@example.com"]
    assert "/auth/verify?token=tok456" in message.body


@pytest.mark.django_db
def test_mail_connection_falls_back_to_default_when_no_host():
    """No email_host configured → use the project default backend (locmem in
    tests), not an SMTP connection."""
    conn = _mail_connection()
    assert not isinstance(conn, SmtpBackend)


@pytest.mark.django_db
def test_mail_connection_builds_smtp_from_app_settings():
    """email_host configured → SMTP connection built from the DB settings."""
    AppSetting.objects.create(
        key="email_host", value="smtp.example.com", category="email"
    )
    AppSetting.objects.create(key="email_port", value=2525, category="email")
    AppSetting.objects.create(key="email_host_user", value="mailer", category="email")
    AppSetting.objects.create(
        key="email_host_password", value="secret", category="email"
    )
    AppSetting.objects.create(key="email_use_tls", value=False, category="email")

    conn = _mail_connection()
    assert isinstance(conn, SmtpBackend)
    assert conn.host == "smtp.example.com"
    assert conn.port == 2525
    assert conn.username == "mailer"
    assert conn.password == "secret"
    assert conn.use_tls is False
