"""Deezer track ids are stored only from the song's own release."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from library_manager.models import Album, Artist, Song
from library_manager.release_ids import (
    SELECT_AMBIGUOUS,
    SELECT_FOUND,
    SELECT_NONE,
    fits_release,
    resolve_release_deezer_id,
    select_release_track,
)
from library_manager.tasks.maintenance import _try_resolve_to_deezer
from library_manager.tasks.migration import _link_or_create_song
from library_manager.tasks.song_identity import release_track_id
from src.providers.metadata_base import TrackResult

ISRC = "TESTGUARD001"


def _track(deezer_id, album_id, isrc=ISRC, pos=1, disc=1):
    return TrackResult(
        name="Test Track",
        artist_name="Synthetic Artist",
        deezer_id=deezer_id,
        isrc=isrc,
        album_deezer_id=album_id,
        album_name="Test Album",
        track_number=pos,
        disc_number=disc,
    )


@pytest.fixture
def artist():
    return Artist.objects.create(name="Synthetic Artist", deezer_id=7720001)


@pytest.fixture
def album(artist):
    return Album.objects.create(name="Test Album", artist=artist, deezer_id=7720010)


@pytest.fixture
def song(artist, album):
    return Song.objects.create(
        name="Test Track",
        gid="g" * 22,
        primary_artist=artist,
        album=album,
        isrc=ISRC,
        deezer_id=None,
    )


@pytest.mark.django_db
def test_select_release_track_outcomes(song):
    assert select_release_track(song, []).status == SELECT_NONE
    found = select_release_track(song, [_track(1, 7720010), _track(2, 7720010, "X")])
    assert found.status == SELECT_FOUND and found.track.deezer_id == 1
    twice = [_track(1, 7720010, pos=1), _track(2, 7720010, pos=4, disc=2)]
    assert select_release_track(song, twice).status == SELECT_AMBIGUOUS
    narrowed = select_release_track(song, twice, position=(2, 4))
    assert narrowed.track.deezer_id == 2


@pytest.mark.django_db
def test_fits_release_requires_an_authoritative_album_id(song):
    """Finding 1: title/artist fallback must never authorize an id write."""
    assert fits_release(song, _track(1, 7720010))
    assert not fits_release(song, _track(1, 7720099))
    # Same title/artist credits on another release: still not this release.
    borrowed = _track(1, 7720099)
    assert not fits_release(song, borrowed)
    # No album Deezer id at all: unverifiable, never write.
    album = song.album
    album.youtube_id = "yt-fixture"  # keep the external-id constraint satisfied
    album.deezer_id = None
    album.save(update_fields=["youtube_id", "deezer_id"])
    song.refresh_from_db()
    assert not fits_release(song, _track(1, 7720099))
    # Track without an album id is also unverifiable.
    album.deezer_id = 7720010
    album.save(update_fields=["deezer_id"])
    song.refresh_from_db()
    assert not fits_release(song, _track(1, None))
    song.album = None
    song.album_id = None
    assert fits_release(song, _track(1, 7720099))


@pytest.mark.django_db
def test_release_track_id_hides_other_releases(song):
    assert release_track_id(song, _track(1, 7720010)) == 1
    assert release_track_id(song, _track(1, 7720099)) is None


@pytest.mark.django_db
def test_resolve_uses_album_track_list_only(song):
    provider = MagicMock()
    provider.get_album_tracks.return_value = [_track(41, 7720010)]
    assert resolve_release_deezer_id(song, provider) == 41
    provider.get_album_tracks.assert_called_once_with(7720010)
    provider.get_album_tracks.return_value = [_track(41, 7720010, isrc="OTHER")]
    assert resolve_release_deezer_id(song, provider) is None
    provider.get_album_tracks.side_effect = RuntimeError("down")
    assert resolve_release_deezer_id(song, provider) is None


@pytest.mark.django_db
def test_try_resolve_ignores_isrc_hit_on_another_release(song):
    provider = MagicMock()
    # The ISRC lookup returns the same recording on the artist's EP.
    provider.get_track_by_isrc.return_value = _track(900, 7720099)
    provider.get_album_tracks.return_value = [_track(41, 7720010)]
    with patch("src.providers.deezer.DeezerMetadataProvider", return_value=provider):
        _try_resolve_to_deezer(song)
    song.refresh_from_db()
    assert song.deezer_id == 41


@pytest.mark.django_db
def test_try_resolve_never_borrows_when_album_lacks_the_track(song):
    provider = MagicMock()
    provider.get_track_by_isrc.return_value = _track(900, 7720099)
    provider.get_album_tracks.return_value = []
    provider.search_tracks.return_value = [_track(901, 7720099)]
    provider.search_tracks.return_value[0].name = song.name
    with patch("src.providers.deezer.DeezerMetadataProvider", return_value=provider):
        _try_resolve_to_deezer(song)
    song.refresh_from_db()
    assert song.deezer_id is None


@pytest.mark.django_db
def test_try_resolve_keeps_isrc_hit_on_the_songs_own_release(song):
    provider = MagicMock()
    provider.get_track_by_isrc.return_value = _track(77, 7720010)
    with patch("src.providers.deezer.DeezerMetadataProvider", return_value=provider):
        _try_resolve_to_deezer(song)
    song.refresh_from_db()
    assert song.deezer_id == 77
    provider.get_album_tracks.assert_not_called()


@pytest.mark.django_db
def test_migration_does_not_link_a_song_from_another_album(artist, song):
    other = Album.objects.create(name="Other", artist=artist, deezer_id=7720020)
    track = _track(555, 7720020)
    with patch(
        "library_manager.tasks.migration.create_song_with_credits",
        return_value=SimpleNamespace(pk=1),
    ) as create:
        result = _link_or_create_song(track, artist, other)
    assert result == "created"
    create.assert_called_once()
    song.refresh_from_db()
    assert song.deezer_id is None


@pytest.mark.django_db
def test_migration_still_links_an_orphan_or_same_album_song(artist, album, song):
    track = _track(555, 7720010)
    with (
        patch("library_manager.tasks.migration.ensure_song_credits"),
        patch("library_manager.tasks.migration.credits_for_song_release"),
    ):
        result = _link_or_create_song(track, artist, album)
    assert result == "linked"
    song.refresh_from_db()
    assert song.deezer_id == 555


@pytest.mark.django_db
def test_enrichment_resolves_albumed_songs_through_their_own_album(song):
    from src.queuetip.enrichment import enrich_song_cross_platform

    song.gid = "q" * 22
    song.save(update_fields=["gid"])
    with (
        patch("library_manager.release_ids.resolve_release_deezer_id", return_value=61),
        patch("src.queuetip.enrichment.get_deezer_id_by_isrc") as by_isrc,
    ):
        result = enrich_song_cross_platform(song)
    by_isrc.assert_not_called()
    assert result.deezer_id == 61
