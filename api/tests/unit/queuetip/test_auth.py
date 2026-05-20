from unittest.mock import patch

import pytest

from src.queuetip import auth


def test_magic_link_token_round_trip():
    token = auth.make_magic_link_token(42)
    assert auth.read_magic_link_token(token) == 42


def test_session_token_round_trip():
    token = auth.make_session_token(7, session_epoch=3)
    payload = auth.read_session_token(token)
    assert payload.account_id == 7
    assert payload.session_epoch == 3


def test_session_token_default_epoch_is_zero():
    token = auth.make_session_token(5)
    payload = auth.read_session_token(token)
    assert payload.account_id == 5
    assert payload.session_epoch == 0


def test_session_token_legacy_no_ep_field_treated_as_epoch_zero():
    """Tokens without the 'ep' key (issued before session epoch) default to 0."""
    from django.core import signing

    legacy_token = signing.dumps({"aid": 99}, salt="queuetip.session")
    payload = auth.read_session_token(legacy_token)
    assert payload.account_id == 99
    assert payload.session_epoch == 0


def test_magic_and_session_tokens_are_not_interchangeable():
    magic = auth.make_magic_link_token(1)
    with pytest.raises(auth.InvalidTokenError):
        auth.read_session_token(magic)


def test_tampered_token_rejected():
    token = auth.make_magic_link_token(1)
    with pytest.raises(auth.InvalidTokenError):
        auth.read_magic_link_token(token + "x")


def test_expired_magic_link_token_rejected():
    token = auth.make_magic_link_token(1)
    with patch.object(auth, "MAGIC_LINK_MAX_AGE", -1):
        with pytest.raises(auth.InvalidTokenError):
            auth.read_magic_link_token(token)
