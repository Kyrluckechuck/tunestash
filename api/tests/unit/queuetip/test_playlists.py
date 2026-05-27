from unittest.mock import patch

import pytest

from src.queuetip.resolution.errors import UnsupportedURLError
from src.queuetip.resolution.playlists import resolve_collection, resolve_playlist


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


def test_resolve_collection_dispatches_spotify_album_uri():
    with patch(
        "src.queuetip.resolution.playlists.resolve_spotify_album",
        return_value=["spotify-album"],
    ) as mock:
        result = resolve_collection("spotify:album:abc")
    assert result == ["spotify-album"]
    mock.assert_called_once()


def test_resolve_collection_dispatches_spotify_localized_share_urls():
    with (
        patch(
            "src.queuetip.resolution.playlists.resolve_spotify_album",
            return_value=["spotify-album"],
        ) as mock_album,
        patch(
            "src.queuetip.resolution.playlists.resolve_spotify_playlist",
            return_value=["spotify-playlist"],
        ) as mock_playlist,
    ):
        assert resolve_collection("https://open.spotify.com/intl-en/album/abc") == [
            "spotify-album"
        ]
        assert resolve_collection("https://open.spotify.com/intl-en/playlist/def") == [
            "spotify-playlist"
        ]
    mock_album.assert_called_once()
    mock_playlist.assert_called_once()


def test_resolve_collection_dispatches_apple_album():
    with patch(
        "src.queuetip.resolution.playlists.resolve_apple_album",
        return_value=["apple-album"],
    ) as mock:
        result = resolve_collection("https://music.apple.com/ca/album/x/123")
    assert result == ["apple-album"]
    mock.assert_called_once()


def test_resolve_collection_rejects_apple_album_url_for_a_specific_track():
    with patch("src.queuetip.resolution.playlists.resolve_apple_album") as mock:
        with pytest.raises(UnsupportedURLError):
            resolve_collection("https://music.apple.com/ca/album/x/123?l=en&i=456")
    mock.assert_not_called()


def test_resolve_collection_dispatches_deezer_album_and_playlist():
    with patch(
        "src.queuetip.resolution.playlists.resolve_deezer_collection",
        side_effect=[["deezer-album"], ["deezer-playlist"]],
    ) as mock:
        assert resolve_collection("https://www.deezer.com/album/42") == ["deezer-album"]
        assert resolve_collection("https://www.deezer.com/playlist/84") == [
            "deezer-playlist"
        ]
    assert mock.call_count == 2
