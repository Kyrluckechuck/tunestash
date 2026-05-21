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
    assert job.total_tracks == 3
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
def test_bulk_import_sets_total_tracks_before_processing() -> None:
    """`total_tracks` must be persisted right after resolve and before any
    ingest work, so a UI polling at 2s sees the count and can render
    'X / Y processed' for the entire duration of the run.
    """
    owner = _make_owner()
    playlist = _make_playlist(owner)
    job = _make_job(owner, playlist)

    candidates = [_make_candidate(f"Song {i}") for i in range(5)]
    songs = [_make_song(f"Song {i}") for i in range(5)]

    seen_total_during_ingest: list[int | None] = []

    def ingest_side_effect(candidate: TrackCandidate) -> object:
        # Each call samples what the persisted total_tracks is mid-run.
        job.refresh_from_db()
        seen_total_during_ingest.append(job.total_tracks)
        return songs[int(candidate.track_name.split()[-1])]

    with (
        patch("queuetip.tasks.resolve_playlist", return_value=candidates),
        patch("queuetip.tasks.ingest_track", side_effect=ingest_side_effect),
    ):
        bulk_import_playlist(job.id)

    # total_tracks set BEFORE any ingest call ran.
    assert seen_total_during_ingest == [5, 5, 5, 5, 5]


@pytest.mark.django_db(transaction=True)
def test_bulk_import_writes_counters_per_track() -> None:
    """Each candidate produces a counter update — the polling UI must be able
    to observe added_count advancing as the run progresses."""
    owner = _make_owner()
    playlist = _make_playlist(owner)
    job = _make_job(owner, playlist)

    candidates = [_make_candidate(f"Song {i}") for i in range(3)]
    songs = [_make_song(f"Song {i}") for i in range(3)]

    seen_added_counts: list[int] = []

    def ingest_side_effect(candidate: TrackCandidate) -> object:
        job.refresh_from_db()
        seen_added_counts.append(job.added_count)
        return songs[int(candidate.track_name.split()[-1])]

    with (
        patch("queuetip.tasks.resolve_playlist", return_value=candidates),
        patch("queuetip.tasks.ingest_track", side_effect=ingest_side_effect),
    ):
        bulk_import_playlist(job.id)

    # Before each ingest, added_count reflects only earlier tracks.
    assert seen_added_counts == [0, 1, 2]
    job.refresh_from_db()
    assert job.added_count == 3


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
