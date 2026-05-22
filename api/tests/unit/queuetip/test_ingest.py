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
        # Default: name+artist fallback finds nothing (tests opt in explicitly).
        patch(
            "src.queuetip.resolution.ingest.find_spotify_track_by_name_artist",
            return_value=None,
        ) as name_search,
    ):
        yield {"deezer": dz, "spotify": sp, "name_search": name_search}


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


def test_ingest_matches_existing_by_alternate_isrc(_no_real_downloads):
    """A recorded alternate ISRC lets a cross-platform import match instantly."""
    artist = ArtistFactory()
    existing = SongFactory(
        primary_artist=artist,
        gid="canon-gid",
        isrc="CANON009",
        alternate_isrcs=["APPLE025"],
    )
    cand = TrackCandidate("Aint It Fun", "Paramore", "apple", isrc="APPLE025")
    result = ingest_track(cand)
    assert result.id == existing.id


def test_ingest_apple_fallback_reuses_existing_and_records_alternate(
    _no_real_downloads,
):
    """ISRC misses Deezer → name+artist search resolves to an existing row by
    its canonical ISRC; the Apple ISRC is saved as an alternate for next time."""
    artist = ArtistFactory()
    existing = SongFactory(primary_artist=artist, gid="canon-gid", isrc="CANON009")
    cand = TrackCandidate("Aint It Fun", "Paramore", "apple", isrc="APPLE025")

    provider = MagicMock()
    provider.get_track_by_isrc.return_value = None  # Deezer ISRC miss
    _no_real_downloads["name_search"].return_value = ("some-gid", "CANON009")
    with patch(
        "src.queuetip.resolution.ingest.DeezerMetadataProvider", return_value=provider
    ):
        result = ingest_track(cand)

    assert result.id == existing.id
    existing.refresh_from_db()
    assert "APPLE025" in existing.alternate_isrcs


def test_ingest_apple_fallback_creates_with_canonical_isrc(_no_real_downloads):
    """No existing row → create with the resolved gid + canonical ISRC, keeping
    the source ISRC as an alternate."""
    cand = TrackCandidate("Some Track", "Some Artist", "apple", isrc="APPLE777")
    provider = MagicMock()
    provider.get_track_by_isrc.return_value = None
    _no_real_downloads["name_search"].return_value = ("new-gid", "CANON111")
    with patch(
        "src.queuetip.resolution.ingest.DeezerMetadataProvider", return_value=provider
    ):
        result = ingest_track(cand)

    assert result.gid == "new-gid"
    assert result.isrc == "CANON111"
    assert result.alternate_isrcs == ["APPLE777"]
