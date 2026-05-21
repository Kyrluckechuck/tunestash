"""Tests for the bulk_import_playlist Celery task."""

from unittest.mock import patch

import pytest
from tests.factories import ArtistFactory, SongFactory

from queuetip.models import (
    Account,
    BulkImportJob,
    Contribution,
    Playlist,
    PlaylistMembership,
)
from queuetip.tasks import bulk_import_playlist
from src.queuetip.resolution.candidate import TrackCandidate
from src.queuetip.resolution.errors import UnsupportedURLError


def _make_candidate(name: str = "Track", artist: str = "Artist") -> TrackCandidate:
    return TrackCandidate(
        track_name=name, artist_name=artist, source="spotify", source_id="x"
    )


def _make_owner() -> Account:
    return Account.objects.create(display_name="Owner")


def _make_playlist(owner: Account) -> Playlist:
    playlist = Playlist.objects.create(name="Test Playlist", created_by=owner)
    PlaylistMembership.objects.create(
        account=owner, playlist=playlist, role=PlaylistMembership.ROLE_OWNER
    )
    return playlist


def _make_job(owner: Account, playlist: Playlist) -> BulkImportJob:
    return BulkImportJob.objects.create(
        playlist=playlist,
        requested_by=owner,
        source_url="https://open.spotify.com/playlist/abc",
    )


def _make_song(name: str = "Song") -> object:
    artist = ArtistFactory(name="Artist")
    return SongFactory(primary_artist=artist, name=name)


@pytest.mark.django_db(transaction=True)
def test_bulk_import_happy_path() -> None:
    owner = _make_owner()
    playlist = _make_playlist(owner)
    job = _make_job(owner, playlist)

    candidates = [
        _make_candidate("Song 1"),
        _make_candidate("Song 2"),
        _make_candidate("Song 3"),
    ]
    songs = [_make_song(f"Song {i}") for i in range(1, 4)]

    with (
        patch(
            "queuetip.tasks.resolve_playlist", return_value=candidates
        ) as mock_resolve,
        patch("queuetip.tasks.ingest_track", side_effect=songs),
    ):
        result = bulk_import_playlist(job.id)

    assert result["status"] == "succeeded"
    assert result["added"] == 3
    assert result["skipped"] == 0
    assert result["unresolved"] == 0

    job.refresh_from_db()
    assert job.status == BulkImportJob.STATUS_SUCCEEDED
    assert job.added_count == 3
    assert job.skipped_count == 0
    assert job.unresolved_count == 0
    assert job.finished_at is not None

    assert Contribution.objects.filter(playlist=playlist).count() == 3
    mock_resolve.assert_called_once_with("https://open.spotify.com/playlist/abc")


@pytest.mark.django_db(transaction=True)
def test_bulk_import_bad_url() -> None:
    owner = _make_owner()
    playlist = _make_playlist(owner)
    job = _make_job(owner, playlist)

    with patch(
        "queuetip.tasks.resolve_playlist",
        side_effect=UnsupportedURLError("YouTube not supported"),
    ):
        result = bulk_import_playlist(job.id)

    assert result["status"] == "failed"
    assert "YouTube not supported" in result["error"]

    job.refresh_from_db()
    assert job.status == BulkImportJob.STATUS_FAILED
    assert "YouTube not supported" in job.error
    assert job.finished_at is not None

    assert Contribution.objects.filter(playlist=playlist).count() == 0


@pytest.mark.django_db(transaction=True)
def test_bulk_import_per_track_failure() -> None:
    owner = _make_owner()
    playlist = _make_playlist(owner)
    job = _make_job(owner, playlist)

    candidates = [
        _make_candidate("Song 1"),
        _make_candidate("Song 2", "Artist B"),
        _make_candidate("Song 3"),
    ]
    song1 = _make_song("Song 1")
    song3 = _make_song("Song 3")

    def ingest_side_effect(candidate: TrackCandidate) -> object:
        if candidate.track_name == "Song 2":
            raise Exception("network")
        if candidate.track_name == "Song 1":
            return song1
        return song3

    with (
        patch("queuetip.tasks.resolve_playlist", return_value=candidates),
        patch("queuetip.tasks.ingest_track", side_effect=ingest_side_effect),
    ):
        result = bulk_import_playlist(job.id)

    assert result["status"] == "succeeded"
    assert result["added"] == 2
    assert result["unresolved"] == 1

    job.refresh_from_db()
    assert job.status == BulkImportJob.STATUS_SUCCEEDED
    assert job.added_count == 2
    assert job.unresolved_count == 1
    assert len(job.unresolved_titles) == 1
    assert "Song 2" in job.unresolved_titles[0]
    assert "Artist B" in job.unresolved_titles[0]


@pytest.mark.django_db(transaction=True)
def test_bulk_import_skip_already_contributed() -> None:
    owner = _make_owner()
    playlist = _make_playlist(owner)
    job = _make_job(owner, playlist)

    candidates = [
        _make_candidate("Song 1"),
        _make_candidate("Song 2"),
    ]
    song1 = _make_song("Song 1")
    song2 = _make_song("Song 2")

    Contribution.objects.create(playlist=playlist, song=song1, contributed_by=owner)

    with (
        patch("queuetip.tasks.resolve_playlist", return_value=candidates),
        patch("queuetip.tasks.ingest_track", side_effect=[song1, song2]),
    ):
        result = bulk_import_playlist(job.id)

    assert result["status"] == "succeeded"
    assert result["added"] == 1
    assert result["skipped"] == 1

    job.refresh_from_db()
    assert job.skipped_count == 1
    assert Contribution.objects.filter(playlist=playlist).count() == 2


@pytest.mark.django_db(transaction=True)
def test_bulk_import_idempotent_rerun() -> None:
    owner = _make_owner()
    playlist = _make_playlist(owner)
    job = _make_job(owner, playlist)

    candidates = [_make_candidate("Song 1")]
    song1 = _make_song("Song 1")

    with (
        patch(
            "queuetip.tasks.resolve_playlist", return_value=candidates
        ) as mock_resolve,
        patch("queuetip.tasks.ingest_track", return_value=song1),
    ):
        result1 = bulk_import_playlist(job.id)
        result2 = bulk_import_playlist(job.id)

    assert result1["status"] == "succeeded"
    assert result2["status"] == BulkImportJob.STATUS_SUCCEEDED
    assert mock_resolve.call_count == 1
