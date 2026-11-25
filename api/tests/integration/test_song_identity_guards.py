"""Identity guards must stop ISRC conflicts from being linked to wrong Deezer tracks."""

from unittest.mock import patch

import pytest

from library_manager.models import Album, Artist, Song, TrackedPlaylist
from library_manager.tasks.migration import _find_matching_song, _link_or_create_song
from library_manager.tasks.playlist import _sync_tracked_playlist_internal
from src.providers.metadata_base import TrackResult


@pytest.fixture
def identity_artist():
    return Artist.objects.create(name="Identity Test Artist", deezer_id=8800001)


def _track(isrc: str, deezer_id: int) -> TrackResult:
    return TrackResult(
        name="Shut Up And Dance",
        artist_name="Identity Test Artist",
        album_name="Shut Up And Dance",
        deezer_id=deezer_id,
        isrc=isrc,
        duration_ms=147000,
        artist_deezer_id=8800001,
        album_deezer_id=8800101,
    )


def _song(artist, *, isrc, alternate_isrcs=None, gid):
    return Song.objects.create(
        name="Shut Up And Dance",
        gid=gid,
        primary_artist=artist,
        isrc=isrc,
        alternate_isrcs=alternate_isrcs or [],
    )


@pytest.mark.django_db
def test_fuzzy_match_skips_song_with_conflicting_isrc(identity_artist):
    _song(identity_artist, isrc="TEST00000001", gid="gid-identity-a")

    result = _find_matching_song(_track("TEST00000002", 9000000002), identity_artist)

    assert result is None


@pytest.mark.django_db
def test_fuzzy_match_accepts_isrc_in_alternate_isrcs(identity_artist):
    song = _song(
        identity_artist,
        isrc="TEST00000001",
        alternate_isrcs=["TEST00000002"],
        gid="gid-identity-b",
    )

    result = _find_matching_song(_track("TEST00000002", 9000000002), identity_artist)

    assert result == song


@pytest.mark.django_db
def test_link_or_create_does_not_overwrite_conflicting_isrc_with_deezer_id(
    identity_artist,
):
    song = _song(identity_artist, isrc="TEST00000001", gid="gid-identity-c")
    album = Album.objects.create(
        name="Shut Up And Dance", artist=identity_artist, deezer_id=8800101
    )

    with patch("library_manager.tasks.migration.logger") as log:
        outcome = _link_or_create_song(
            _track("TEST00000002", 9000000002), identity_artist, album
        )

    song.refresh_from_db()
    assert song.deezer_id is None
    assert song.isrc == "TEST00000001"
    assert outcome == "created"
    assert "isrc conflict" in " ".join(str(c) for c in log.info.call_args_list).lower()


@pytest.mark.django_db
def test_link_or_create_links_when_isrcs_match(identity_artist):
    song = _song(identity_artist, isrc="TEST00000001", gid="gid-identity-d")
    album = Album.objects.create(
        name="Shut Up And Dance", artist=identity_artist, deezer_id=8800101
    )

    outcome = _link_or_create_song(
        _track("TEST00000001", 9000000001), identity_artist, album
    )

    song.refresh_from_db()
    assert outcome == "linked"
    assert song.deezer_id == 9000000001


@pytest.mark.django_db
def test_playlist_sync_does_not_attach_conflicting_deezer_id(identity_artist):
    song = _song(identity_artist, isrc="TEST00000001", gid="gid-identity-e")
    playlist = TrackedPlaylist.objects.create(
        name="Identity playlist",
        url="https://www.deezer.com/playlist/8800001",
        provider="deezer",
    )
    track = _track("TEST00000002", 9000000002)

    class FakeProvider:
        def get_playlist(self, playlist_id):
            return None

        def get_playlist_tracks(self, playlist_id):
            return [track]

    with (
        patch(
            "src.providers.deezer.DeezerMetadataProvider",
            return_value=FakeProvider(),
        ),
        patch("library_manager.tasks.playlist.helpers.enqueue_download_deezer_track"),
    ):
        _sync_tracked_playlist_internal(playlist, None)

    song.refresh_from_db()
    assert song.deezer_id is None
    assert song.isrc == "TEST00000001"
