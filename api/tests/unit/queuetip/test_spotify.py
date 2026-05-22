from unittest.mock import MagicMock, patch

import pytest
import spotipy

from src.queuetip.resolution.errors import (
    EditorialPlaylistError,
    ResolutionError,
    TrackNotFoundError,
)
from src.queuetip.resolution.spotify import (
    resolve_spotify_playlist,
    resolve_spotify_track,
)


def _items_page(tracks, next_url=None):
    return {
        "items": [{"track": t} for t in tracks],
        "next": next_url,
    }


def _track(name, artists, isrc, tid):
    return {
        "name": name,
        "id": tid,
        "artists": [{"name": a} for a in artists],
        "external_ids": {"isrc": isrc},
    }


@pytest.fixture
def fake_spotify():
    sp = MagicMock()
    yield sp


def test_resolve_spotify_playlist_paginates(fake_spotify):
    page1 = _items_page([_track("A", ["X"], "ISRC1", "t1")], next_url="page2")
    page2 = _items_page([_track("B", ["Y", "Z"], "ISRC2", "t2")], next_url=None)
    fake_spotify.playlist_items.return_value = page1
    fake_spotify.next.return_value = page2
    with patch(
        "src.queuetip.resolution.spotify._build_client", return_value=fake_spotify
    ):
        result = resolve_spotify_playlist("https://open.spotify.com/playlist/abc123")
    assert [c.track_name for c in result] == ["A", "B"]
    assert result[1].artist_name == "Y"  # primary artist only
    assert result[1].all_artists == ["Y", "Z"]
    assert result[0].isrc == "ISRC1"
    assert result[0].source == "spotify"


def test_resolve_spotify_playlist_editorial_404(fake_spotify):
    fake_spotify.playlist_items.side_effect = spotipy.SpotifyException(
        404, -1, "not found"
    )
    with patch(
        "src.queuetip.resolution.spotify._build_client", return_value=fake_spotify
    ):
        with pytest.raises(EditorialPlaylistError):
            resolve_spotify_playlist(
                "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"
            )


def test_resolve_spotify_track_happy_path():
    track_data = _track("Song Title", ["Artist A", "Artist B"], "USRC12345678", "tid1")
    fake_sp = MagicMock()
    fake_sp.track.return_value = track_data
    with patch("src.queuetip.resolution.spotify._build_client", return_value=fake_sp):
        candidate = resolve_spotify_track("https://open.spotify.com/track/tid1")
    assert candidate.track_name == "Song Title"
    assert candidate.source == "spotify"
    assert candidate.source_id == "tid1"
    assert candidate.isrc == "USRC12345678"


def test_resolve_spotify_track_bad_url():
    with pytest.raises(TrackNotFoundError):
        resolve_spotify_track("https://open.spotify.com/album/xyz")


def test_resolve_spotify_playlist_missing_credentials():
    with patch("src.queuetip.resolution.spotify.get_setting", return_value=None):
        with pytest.raises(ResolutionError):
            resolve_spotify_playlist("https://open.spotify.com/playlist/abc")
