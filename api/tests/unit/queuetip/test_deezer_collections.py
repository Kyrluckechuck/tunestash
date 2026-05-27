from unittest.mock import MagicMock, patch

import httpx
import pytest

from src.queuetip.resolution.deezer import resolve_deezer_collection
from src.queuetip.resolution.errors import PlaylistNotFoundError


def _track(track_id: int) -> MagicMock:
    track = MagicMock()
    track.name = f"Track {track_id}"
    track.artist_name = "Artist"
    track.isrc = f"ISRC{track_id}"
    track.deezer_id = track_id
    return track


def test_resolve_deezer_album_builds_candidates() -> None:
    provider = MagicMock()
    provider.get_album_tracks.return_value = [_track(42)]
    with patch(
        "src.queuetip.resolution.deezer.DeezerMetadataProvider", return_value=provider
    ):
        result = resolve_deezer_collection("https://www.deezer.com/album/1")
    assert result[0].source == "deezer"
    assert result[0].source_id == "42"
    provider.get_album_tracks.assert_called_once_with("1")


def test_resolve_deezer_playlist_builds_candidates() -> None:
    provider = MagicMock()
    provider.get_playlist_tracks.return_value = [_track(84)]
    with patch(
        "src.queuetip.resolution.deezer.DeezerMetadataProvider", return_value=provider
    ):
        result = resolve_deezer_collection("https://www.deezer.com/playlist/2")
    assert result[0].source_id == "84"
    provider.get_playlist_tracks.assert_called_once_with("2")


def test_resolve_deezer_collection_converts_provider_failure() -> None:
    provider = MagicMock()
    provider.get_album_tracks.side_effect = httpx.HTTPError("provider unavailable")
    with patch(
        "src.queuetip.resolution.deezer.DeezerMetadataProvider", return_value=provider
    ):
        with pytest.raises(PlaylistNotFoundError):
            resolve_deezer_collection("https://www.deezer.com/album/1")
