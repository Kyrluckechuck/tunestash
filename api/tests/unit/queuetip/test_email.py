import pytest

from src.queuetip.email import (
    magic_link_url,
    password_reset_url,
    send_magic_link_email,
    send_password_reset_email,
)


def test_magic_link_url_includes_token():
    url = magic_link_url("abc123")
    assert url.endswith("/auth/verify?token=abc123")
    assert "://" in url


@pytest.mark.django_db
def test_send_magic_link_email_delivers_with_link(mailoutbox):
    send_magic_link_email("friend@example.com", "tok456", "AB12CD34")
    assert len(mailoutbox) == 1
    message = mailoutbox[0]
    assert message.to == ["friend@example.com"]
    assert "/auth/verify?token=tok456" in message.body
    assert "AB12CD34" in message.body


def test_password_reset_url_includes_token():
    url = password_reset_url("rst123")
    assert "/sign-in?resetToken=rst123" in url


@pytest.mark.django_db
def test_send_password_reset_email_delivers_with_link(mailoutbox):
    send_password_reset_email("friend@example.com", "reset_token")
    assert len(mailoutbox) == 1
    message = mailoutbox[0]
    assert message.to == ["friend@example.com"]
    assert "/sign-in?resetToken=reset_token" in message.body
