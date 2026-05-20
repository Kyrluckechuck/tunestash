"""Unit tests for the Queuetip Spotify OAuth state-signing helpers."""

from unittest.mock import patch

import pytest

from src.queuetip import spotify_oauth


def test_state_round_trip():
    token = spotify_oauth.make_state_token(42)
    assert spotify_oauth.read_state_token(token) == 42


def test_tampered_state_rejected():
    token = spotify_oauth.make_state_token(1)
    with pytest.raises(spotify_oauth.InvalidStateError):
        spotify_oauth.read_state_token(token + "x")


def test_expired_state_rejected():
    token = spotify_oauth.make_state_token(1)
    with patch.object(spotify_oauth, "STATE_MAX_AGE", -1):
        with pytest.raises(spotify_oauth.InvalidStateError):
            spotify_oauth.read_state_token(token)


def test_build_authorize_url_includes_state_and_scope():
    with patch.object(spotify_oauth, "get_credentials", return_value=("cid", "sec")):
        url = spotify_oauth.build_authorize_url(
            state="abc", redirect_uri="http://localhost:5050/auth/spotify/callback"
        )
    assert "state=abc" in url
    assert "client_id=cid" in url
    assert "scope=playlist-modify-private+playlist-modify-public" in url


def test_build_authorize_url_points_to_spotify():
    with patch.object(spotify_oauth, "get_credentials", return_value=("cid", "sec")):
        url = spotify_oauth.build_authorize_url(
            state="tok", redirect_uri="http://localhost:5050/auth/spotify/callback"
        )
    assert url.startswith("https://accounts.spotify.com/authorize")


def test_get_credentials_raises_when_missing():
    with patch.object(
        spotify_oauth,
        "get_setting",
        side_effect=lambda k: "",
    ):
        with pytest.raises(spotify_oauth.SpotifyOAuthError, match="not configured"):
            spotify_oauth.get_credentials()
