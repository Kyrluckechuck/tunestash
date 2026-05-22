from unittest.mock import MagicMock, patch

import pytest
from tests.factories import ArtistFactory, SongFactory

from library_manager.models import Song
from src.queuetip.resolution.candidate import TrackCandidate
from src.queuetip.resolution.errors import TrackNotFoundError
from src.queuetip.resolution.ingest import (
    _QUEUETIP_DOWNLOAD_PRIORITY,
    _QUEUETIP_DOWNLOAD_QUEUE,
    ingest_track,
)


@pytest.fixture(autouse=True)
def _no_real_downloads():
    with (
        patch("src.queuetip.resolution.ingest.download_deezer_track") as dz,
        patch("src.queuetip.resolution.ingest.download_track_by_spotify_gid") as sp,
        patch(
            "src.queuetip.resolution.ingest.enrich_song_cross_platform",
            side_effect=lambda song: song,
        ),
    ):
        yield {"deezer": dz, "spotify": sp}


def test_ingest_matches_existing_song_by_gid(_no_real_downloads):
    artist = ArtistFactory()
    existing = SongFactory(primary_artist=artist, gid="spot123", downloaded=False)
    cand = TrackCandidate("Song", "Artist", "spotify", source_id="spot123")
    result = ingest_track(cand)
    assert result.id == existing.id
    _no_real_downloads["spotify"].apply_async.assert_called_once_with(
        args=["spot123"],
        queue=_QUEUETIP_DOWNLOAD_QUEUE,
        priority=_QUEUETIP_DOWNLOAD_PRIORITY,
    )


def test_ingest_matches_existing_song_by_isrc(_no_real_downloads):
    artist = ArtistFactory()
    existing = SongFactory(primary_artist=artist, isrc="ISRCMATCH", deezer_id=55)
    cand = TrackCandidate("Song", "Artist", "apple", isrc="ISRCMATCH", source_id="999")
    result = ingest_track(cand)
    assert result.id == existing.id
    assert Song.objects.count() == 1


def test_ingest_creates_spotify_song(_no_real_downloads):
    cand = TrackCandidate(
        "New Song", "New Artist", "spotify", isrc="ISRCNEW", source_id="newgid1"
    )
    result = ingest_track(cand)
    assert result.gid == "newgid1"
    assert result.isrc == "ISRCNEW"
    assert result.primary_artist.name == "New Artist"
    _no_real_downloads["spotify"].apply_async.assert_called_once_with(
        args=["newgid1"],
        queue=_QUEUETIP_DOWNLOAD_QUEUE,
        priority=_QUEUETIP_DOWNLOAD_PRIORITY,
    )


def test_ingest_creates_apple_song_via_isrc_to_deezer(_no_real_downloads):
    deezer_result = MagicMock(deezer_id=7777, artist_deezer_id=12)
    provider = MagicMock()
    provider.get_track_by_isrc.return_value = deezer_result
    cand = TrackCandidate("Apple Song", "Apple Artist", "apple", isrc="ISRCAPPLE")
    with patch(
        "src.queuetip.resolution.ingest.DeezerMetadataProvider", return_value=provider
    ):
        result = ingest_track(cand)
    assert result.deezer_id == 7777
    _no_real_downloads["deezer"].apply_async.assert_called_once_with(
        args=[result.id],
        queue=_QUEUETIP_DOWNLOAD_QUEUE,
        priority=_QUEUETIP_DOWNLOAD_PRIORITY,
    )
    assert result.primary_artist.deezer_id == 12
    assert result.primary_artist.gid is None


def test_ingest_unresolvable_apple_song_raises(_no_real_downloads):
    provider = MagicMock()
    provider.get_track_by_isrc.return_value = None
    cand = TrackCandidate("Ghost", "Nobody", "apple", isrc="NOISRC")
    with patch(
        "src.queuetip.resolution.ingest.DeezerMetadataProvider", return_value=provider
    ):
        with pytest.raises(TrackNotFoundError):
            ingest_track(cand)


def test_ingest_calls_enrich_after_create(_no_real_downloads):
    """enrich_song_cross_platform is called after song creation."""
    cand = TrackCandidate(
        "Enrich Me", "Artist", "spotify", isrc="ISRCENRICH", source_id="gid_enrich"
    )
    with patch(
        "src.queuetip.resolution.ingest.enrich_song_cross_platform",
        side_effect=lambda song: song,
    ) as mock_enrich:
        result = ingest_track(cand)
    mock_enrich.assert_called_once()
    called_song = mock_enrich.call_args[0][0]
    assert called_song.id == result.id
