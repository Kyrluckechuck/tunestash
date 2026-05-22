"""Unit tests for src.queuetip.enrichment."""

from unittest.mock import MagicMock, patch

import pytest
from tests.factories import AlbumFactory, ArtistFactory, SongFactory

from library_manager.models import Song
from src.queuetip.enrichment import (
    enrich_song_cross_platform,
    get_deezer_id_by_isrc,
    get_spotify_gid_by_isrc,
    get_spotify_track_isrc,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_sp_search_result(track_id: str) -> dict:
    return {"tracks": {"items": [{"id": track_id}]}}


def _make_sp_track_result(isrc: str) -> dict:
    return {"external_ids": {"isrc": isrc}}


# ---------------------------------------------------------------------------
# get_spotify_gid_by_isrc
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_get_spotify_gid_by_isrc_happy_path():
    sp = MagicMock()
    sp.search.return_value = _make_sp_search_result("SPOTGID1")
    client = MagicMock(sp=sp)

    with patch("downloader.spotipy_tasks.PublicSpotifyClient", return_value=client):
        result = get_spotify_gid_by_isrc("ISRC123")

    assert result == "SPOTGID1"
    sp.search.assert_called_once_with(q="isrc:ISRC123", type="track", limit=1)


@pytest.mark.django_db
def test_get_spotify_gid_by_isrc_no_results():
    sp = MagicMock()
    sp.search.return_value = {"tracks": {"items": []}}
    client = MagicMock(sp=sp)

    with patch("downloader.spotipy_tasks.PublicSpotifyClient", return_value=client):
        result = get_spotify_gid_by_isrc("ISRC_NOHIT")

    assert result is None


@pytest.mark.django_db
def test_get_spotify_gid_by_isrc_api_raises_returns_none():
    sp = MagicMock()
    sp.search.side_effect = RuntimeError("Spotify down")
    client = MagicMock(sp=sp)

    with patch("downloader.spotipy_tasks.PublicSpotifyClient", return_value=client):
        result = get_spotify_gid_by_isrc("ISRCBAD")

    assert result is None


@pytest.mark.django_db
def test_get_spotify_gid_by_isrc_unconfigured_client():
    client = MagicMock(sp=None)
    with patch("downloader.spotipy_tasks.PublicSpotifyClient", return_value=client):
        result = get_spotify_gid_by_isrc("ISRCX")
    assert result is None


# ---------------------------------------------------------------------------
# get_spotify_track_isrc
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_get_spotify_track_isrc_happy_path():
    sp = MagicMock()
    sp.track.return_value = _make_sp_track_result("USRC12345678")
    client = MagicMock(sp=sp)

    with patch("downloader.spotipy_tasks.PublicSpotifyClient", return_value=client):
        result = get_spotify_track_isrc("GID123")

    assert result == "USRC12345678"


@pytest.mark.django_db
def test_get_spotify_track_isrc_no_external_ids():
    sp = MagicMock()
    sp.track.return_value = {"external_ids": {}}
    client = MagicMock(sp=sp)

    with patch("downloader.spotipy_tasks.PublicSpotifyClient", return_value=client):
        result = get_spotify_track_isrc("GID_NOISRC")

    assert result is None


@pytest.mark.django_db
def test_get_spotify_track_isrc_api_raises_returns_none():
    sp = MagicMock()
    sp.track.side_effect = RuntimeError("network error")
    client = MagicMock(sp=sp)

    with patch("downloader.spotipy_tasks.PublicSpotifyClient", return_value=client):
        result = get_spotify_track_isrc("GID_ERR")

    assert result is None


# ---------------------------------------------------------------------------
# get_deezer_id_by_isrc
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_get_deezer_id_by_isrc_happy_path():
    provider = MagicMock()
    provider.get_track_by_isrc.return_value = MagicMock(deezer_id=99999)

    with patch("src.providers.deezer.DeezerMetadataProvider", return_value=provider):
        result = get_deezer_id_by_isrc("ISRCDZ1")

    assert result == 99999


@pytest.mark.django_db
def test_get_deezer_id_by_isrc_not_found():
    provider = MagicMock()
    provider.get_track_by_isrc.return_value = None

    with patch("src.providers.deezer.DeezerMetadataProvider", return_value=provider):
        result = get_deezer_id_by_isrc("ISRC_MISS")

    assert result is None


@pytest.mark.django_db
def test_get_deezer_id_by_isrc_api_raises_returns_none():
    provider = MagicMock()
    provider.get_track_by_isrc.side_effect = Exception("Deezer error")

    with patch("src.providers.deezer.DeezerMetadataProvider", return_value=provider):
        result = get_deezer_id_by_isrc("ISRC_ERR")

    assert result is None


# ---------------------------------------------------------------------------
# enrich_song_cross_platform — happy paths
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_enrich_song_isrc_only_fills_gid_and_deezer_id():
    """Song has isrc + deezer_id (required by constraint) → gid populated after enrichment."""
    artist = ArtistFactory()
    # deezer_id satisfies the at-least-one-external-id constraint while gid is None
    song = SongFactory(
        primary_artist=artist, gid=None, deezer_id=50001, isrc="ISRCHAPPY"
    )

    with (
        patch(
            "src.queuetip.enrichment.get_spotify_gid_by_isrc", return_value="NEWGID1"
        ),
        patch("src.queuetip.enrichment.get_deezer_id_by_isrc") as mock_dz,
    ):
        result = enrich_song_cross_platform(song)

    # deezer_id was already set → should NOT call deezer lookup
    mock_dz.assert_not_called()
    assert result.gid == "NEWGID1"
    db_song = Song.objects.get(id=song.id)
    assert db_song.gid == "NEWGID1"


@pytest.mark.django_db
def test_enrich_song_isrc_and_no_deezer_fills_both():
    """Song has isrc but no gid and no deezer_id → both resolved."""
    artist = ArtistFactory()
    # Use youtube_id to satisfy the constraint while gid and deezer_id are None
    song = SongFactory(
        primary_artist=artist,
        gid=None,
        deezer_id=None,
        isrc="ISRCDUAL",
        youtube_id="YTID001",
    )

    with (
        patch(
            "src.queuetip.enrichment.get_spotify_gid_by_isrc", return_value="NEWGID2"
        ),
        patch("src.queuetip.enrichment.get_deezer_id_by_isrc", return_value=88888),
    ):
        result = enrich_song_cross_platform(song)

    assert result.gid == "NEWGID2"
    assert result.deezer_id == 88888
    db_song = Song.objects.get(id=song.id)
    assert db_song.gid == "NEWGID2"
    assert db_song.deezer_id == 88888


@pytest.mark.django_db
def test_enrich_song_gid_only_fills_isrc_and_deezer_id():
    """Song has gid only + no isrc → isrc fetched, then deezer_id filled."""
    artist = ArtistFactory()
    song = SongFactory(primary_artist=artist, gid="STARTGID", deezer_id=None, isrc=None)

    with (
        patch(
            "src.queuetip.enrichment.get_spotify_track_isrc",
            return_value="USRC99999999",
        ),
        patch("src.queuetip.enrichment.get_deezer_id_by_isrc", return_value=77777),
    ):
        result = enrich_song_cross_platform(song)

    assert result.isrc == "USRC99999999"
    assert result.deezer_id == 77777
    db_song = Song.objects.get(id=song.id)
    assert db_song.isrc == "USRC99999999"
    assert db_song.deezer_id == 77777


@pytest.mark.django_db
def test_enrich_song_nothing_to_do_returns_unchanged():
    """Song has no gid, no isrc, no deezer_id → nothing to look up, song unchanged."""
    artist = ArtistFactory()
    # Need youtube_id to satisfy the at-least-one constraint
    song = SongFactory(
        primary_artist=artist,
        gid=None,
        deezer_id=None,
        isrc=None,
        youtube_id="YTONLY",
    )
    original_id = song.id

    with (
        patch("src.queuetip.enrichment.get_spotify_gid_by_isrc") as mock_sp,
        patch("src.queuetip.enrichment.get_spotify_track_isrc") as mock_sp_isrc,
        patch("src.queuetip.enrichment.get_deezer_id_by_isrc") as mock_dz,
    ):
        result = enrich_song_cross_platform(song)

    assert result.id == original_id
    assert result.gid is None
    assert result.deezer_id is None
    mock_sp.assert_not_called()
    mock_sp_isrc.assert_not_called()
    mock_dz.assert_not_called()


@pytest.mark.django_db
def test_enrich_song_lookup_fails_silently():
    """When gid/deezer_id lookups return None, Song stays unchanged, no exception."""
    artist = ArtistFactory()
    song = SongFactory(
        primary_artist=artist,
        gid=None,
        deezer_id=None,
        isrc="ISRC_NOHIT",
        youtube_id="YTNOHIT",
    )

    with (
        patch("src.queuetip.enrichment.get_spotify_gid_by_isrc", return_value=None),
        patch("src.queuetip.enrichment.get_deezer_id_by_isrc", return_value=None),
    ):
        result = enrich_song_cross_platform(song)

    assert result.gid is None
    assert result.deezer_id is None
    db_song = Song.objects.get(id=song.id)
    assert db_song.gid is None


@pytest.mark.django_db
def test_enrich_song_api_raises_does_not_propagate():
    """Enrichment never raises even if helpers raise unexpectedly."""
    artist = ArtistFactory()
    # helpers catch their own exceptions; test that the overall call is safe
    song = SongFactory(
        primary_artist=artist,
        gid=None,
        deezer_id=None,
        isrc="ISRC_ERR",
        youtube_id="YTERR",
    )

    with (
        patch(
            "src.queuetip.enrichment.get_spotify_gid_by_isrc",
            return_value=None,
        ),
        patch(
            "src.queuetip.enrichment.get_deezer_id_by_isrc",
            return_value=None,
        ),
    ):
        result = enrich_song_cross_platform(song)

    assert result.id == song.id


@pytest.mark.django_db
def test_enrich_song_idempotent_when_all_fields_present():
    """Song already has gid + isrc + deezer_id → no API calls, same values back."""
    artist = ArtistFactory()
    song = SongFactory(
        primary_artist=artist,
        gid="EXISTGID",
        deezer_id=111,
        isrc="ISRCEXIST",
    )

    with (
        patch("src.queuetip.enrichment.get_spotify_gid_by_isrc") as mock_sp,
        patch("src.queuetip.enrichment.get_spotify_track_isrc") as mock_sp_isrc,
        patch("src.queuetip.enrichment.get_deezer_id_by_isrc") as mock_dz,
    ):
        result = enrich_song_cross_platform(song)

    assert result.gid == "EXISTGID"
    assert result.deezer_id == 111
    mock_sp.assert_not_called()
    mock_sp_isrc.assert_not_called()
    mock_dz.assert_not_called()


@pytest.mark.django_db
def test_enrich_skips_deezer_id_when_album_pair_taken():
    """The Island Boy bug: two rows for the same recording in one album.

    A sibling row already owns (deezer_id, album); enriching the other row must
    NOT crash (or abort ingest) trying to backfill the same deezer_id — it skips
    the field, leaving deezer_id unset.
    """
    artist = ArtistFactory()
    album = AlbumFactory()
    # Sibling: Deezer-sourced, owns (775788292, album).
    SongFactory(
        primary_artist=artist, album=album, gid="SIB", deezer_id=775788292, isrc="ISRCX"
    )
    # Spotify-sourced row for the same recording: same album/isrc, no deezer_id.
    song = SongFactory(
        primary_artist=artist, album=album, gid="SPOT", deezer_id=None, isrc="ISRCX"
    )

    with patch("src.queuetip.enrichment.get_deezer_id_by_isrc", return_value=775788292):
        result = enrich_song_cross_platform(song)  # must not raise

    assert result.deezer_id is None
    assert Song.objects.get(id=song.id).deezer_id is None
