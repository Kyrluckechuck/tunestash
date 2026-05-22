from unittest.mock import patch

import pytest

from src.queuetip.resolution.errors import UnsupportedURLError
from src.queuetip.resolution.playlists import resolve_playlist


def test_resolve_playlist_dispatches_spotify():
    with patch(
        "src.queuetip.resolution.playlists.resolve_spotify_playlist",
        return_value=["spotify-result"],
    ) as mock:
        result = resolve_playlist("https://open.spotify.com/playlist/abc")
    assert result == ["spotify-result"]
    mock.assert_called_once()


def test_resolve_playlist_dispatches_apple():
    with patch(
        "src.queuetip.resolution.playlists.resolve_apple_playlist",
        return_value=["apple-result"],
    ) as mock:
        result = resolve_playlist("https://music.apple.com/ca/playlist/x/pl.u-abc")
    assert result == ["apple-result"]
    mock.assert_called_once()


def test_resolve_playlist_rejects_unknown_host():
    with pytest.raises(UnsupportedURLError):
        resolve_playlist("https://example.com/playlist/123")
