from unittest.mock import patch

import pytest

from src.queuetip import auth


def test_magic_link_token_round_trip():
    token = auth.make_magic_link_token(42)
    assert auth.read_magic_link_token(token) == 42


def test_session_token_round_trip():
    token = auth.make_session_token(7)
    assert auth.read_session_token(token) == 7


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
