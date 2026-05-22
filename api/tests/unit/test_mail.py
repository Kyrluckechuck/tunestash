"""Tests for the shared mail connection helper (src/services/mail.py)."""

from django.core.mail.backends.smtp import EmailBackend as SmtpBackend

import pytest

from library_manager.models import AppSetting
from src.services.mail import (
    build_connection,
    from_address,
    render_email,
    send_message,
)


@pytest.mark.django_db
def test_build_connection_falls_back_to_default_when_no_host():
    """No email_host → project default backend (locmem in tests), not SMTP."""
    assert not isinstance(build_connection(), SmtpBackend)


@pytest.mark.django_db
def test_build_connection_builds_smtp_from_app_settings():
    AppSetting.objects.create(
        key="email_host", value="smtp.example.com", category="email"
    )
    AppSetting.objects.create(key="email_port", value=2525, category="email")
    AppSetting.objects.create(key="email_host_user", value="mailer", category="email")
    AppSetting.objects.create(
        key="email_host_password", value="secret", category="email"
    )
    AppSetting.objects.create(key="email_use_tls", value=False, category="email")

    conn = build_connection()
    assert isinstance(conn, SmtpBackend)
    assert conn.host == "smtp.example.com"
    assert conn.port == 2525
    assert conn.username == "mailer"
    assert conn.password == "secret"
    assert conn.use_tls is False


@pytest.mark.django_db
def test_build_connection_implicit_ssl_for_465():
    """email_use_ssl → implicit SSL (port 465), not STARTTLS."""
    AppSetting.objects.create(
        key="email_host", value="smtp.gmail.com", category="email"
    )
    AppSetting.objects.create(key="email_port", value=465, category="email")
    AppSetting.objects.create(key="email_use_ssl", value=True, category="email")

    conn = build_connection()
    assert conn.use_ssl is True
    assert conn.use_tls is False


@pytest.mark.django_db
def test_build_connection_ssl_wins_when_both_set():
    """STARTTLS + SSL both on → SSL wins (Django errors if both are True)."""
    AppSetting.objects.create(
        key="email_host", value="smtp.gmail.com", category="email"
    )
    AppSetting.objects.create(key="email_use_tls", value=True, category="email")
    AppSetting.objects.create(key="email_use_ssl", value=True, category="email")

    conn = build_connection()
    assert conn.use_ssl is True
    assert conn.use_tls is False


@pytest.mark.django_db
def test_from_address_uses_setting_then_registry_default():
    # No DB override → the registry default for email_from.
    assert from_address() == "Queuetip <queuetip@localhost>"
    AppSetting.objects.create(
        key="email_from", value="TuneStash <no-reply@example.com>", category="email"
    )
    assert from_address() == "TuneStash <no-reply@example.com>"


@pytest.mark.django_db
def test_send_message_delivers(mailoutbox):
    send_message(subject="Hi", body="body text", to="dest@example.com")
    assert len(mailoutbox) == 1
    assert mailoutbox[0].to == ["dest@example.com"]
    assert mailoutbox[0].subject == "Hi"


def test_render_email_escapes_and_includes_button():
    html = render_email(
        eyebrow="Queuetip",
        heading="Sign in",
        paragraphs=["Hello <script>", "second"],
        button=("Go", "https://example.com/x?token=abc"),
        footer="footer note",
    )
    assert "<table" in html and "https://example.com/x?token=abc" in html
    assert "Go" in html and "footer note" in html
    # Dynamic text is escaped, not injected raw.
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


@pytest.mark.django_db
def test_send_message_attaches_html_alternative(mailoutbox):
    send_message(subject="S", body="plain text", to="a@b.com", html_body="<p>rich</p>")
    assert len(mailoutbox) == 1
    msg = mailoutbox[0]
    assert msg.body == "plain text"
    assert msg.alternatives == [("<p>rich</p>", "text/html")]
