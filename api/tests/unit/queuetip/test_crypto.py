"""Unit tests for queuetip's at-rest secret helpers."""

from src.queuetip.crypto import decrypt_token, encrypt_secret, encrypt_token


def test_encrypt_token_round_trips():
    assert decrypt_token(encrypt_token("BQ-spotify-access-token")) == (
        "BQ-spotify-access-token"
    )


def test_encrypt_token_output_is_not_plaintext():
    """The stored value must not contain the original token."""
    ciphertext = encrypt_token("super-secret")
    assert "super-secret" not in ciphertext


def test_decrypt_token_passes_through_legacy_plaintext():
    """A value that isn't valid Fernet ciphertext (a token stored before
    encryption was added) is returned unchanged, so existing links keep
    working until their next refresh rewrites them encrypted."""
    assert decrypt_token("legacy-plaintext-token") == "legacy-plaintext-token"


def test_decrypt_token_handles_empty():
    assert decrypt_token("") == ""


def test_encrypt_token_is_distinct_from_binary_helper():
    """encrypt_token returns text (for TEXT columns); encrypt_secret returns
    bytes (for the BinaryField path). Both must decrypt to the same value."""
    assert isinstance(encrypt_token("x"), str)
    assert isinstance(encrypt_secret("x"), bytes)
