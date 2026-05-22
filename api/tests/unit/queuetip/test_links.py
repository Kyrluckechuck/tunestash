from unittest.mock import MagicMock, patch

import pytest

from src.queuetip.resolution.candidate import TrackCandidate
from src.queuetip.resolution.errors import TrackNotFoundError, UnsupportedURLError
from src.queuetip.resolution.links import resolve_link


def test_resolve_link_spotify():
    cand = TrackCandidate("A", "X", "spotify", source_id="t1")
    with patch(
        "src.queuetip.resolution.links.resolve_spotify_track", return_value=cand
    ):
        assert resolve_link("https://open.spotify.com/track/t1") is cand


def test_resolve_link_apple():
    cand = TrackCandidate("A", "X", "apple", source_id="9")
    with patch("src.queuetip.resolution.links.resolve_apple_track", return_value=cand):
        assert resolve_link("https://music.apple.com/ca/song/x/9") is cand


def test_resolve_link_deezer():
    fake_track = MagicMock()
    fake_track.name = "Maps"
    fake_track.artist_name = "Maroon 5"
    fake_track.isrc = "ISRCX"
    provider = MagicMock()
    provider.get_track.return_value = fake_track
    with patch(
        "src.queuetip.resolution.links.DeezerMetadataProvider", return_value=provider
    ):
        result = resolve_link("https://www.deezer.com/track/42")
    assert result.source == "deezer"
    assert result.source_id == "42"
    assert result.isrc == "ISRCX"
    provider.get_track.assert_called_once_with("42")


def test_resolve_link_deezer_not_found():
    provider = MagicMock()
    provider.get_track.return_value = None
    with patch(
        "src.queuetip.resolution.links.DeezerMetadataProvider", return_value=provider
    ):
        with pytest.raises(TrackNotFoundError):
            resolve_link("https://www.deezer.com/track/999")


def test_resolve_link_youtube_unsupported():
    with pytest.raises(UnsupportedURLError):
        resolve_link("https://music.youtube.com/watch?v=abc")
