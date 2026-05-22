import pytest

from src.queuetip.email import magic_link_url, send_magic_link_email


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
