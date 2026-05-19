"""Tests for queuetip m3u export rendering."""

import pytest
from tests.factories import ArtistFactory, SongFactory

from queuetip.models import (
    Account,
    ExportSnapshot,
    ExportSnapshotTrack,
    Playlist,
)
from src.queuetip.m3u import render_m3u


def _make_owner_and_snap(playlist_name: str = "Test Playlist", rng_seed: int = 1):
    owner = Account.objects.create(display_name="O")
    playlist = Playlist.objects.create(name=playlist_name, created_by=owner)
    snap = ExportSnapshot.objects.create(
        playlist=playlist, requested_by=owner, rng_seed=rng_seed
    )
    return owner, snap


def _add_track(snap, song, position, reason="rolled_in", probability=0.85):
    return ExportSnapshotTrack.objects.create(
        snapshot=snap,
        song=song,
        position=position,
        inclusion_reason=reason,
        roll_probability=probability,
    )


@pytest.mark.django_db
def test_m3u_starts_with_extm3u_header():
    _owner, snap = _make_owner_and_snap("Friday Mix")
    out = render_m3u(snap)
    assert out.startswith("#EXTM3U\n")


@pytest.mark.django_db
def test_m3u_header_includes_playlist_name_and_snapshot_id():
    _owner, snap = _make_owner_and_snap("Friday Mix")
    out = render_m3u(snap)
    assert "Friday Mix" in out
    # Either "snapshot 5" or "snapshot-5" are acceptable per the task spec
    assert f"snapshot {snap.id}" in out or f"snapshot-{snap.id}" in out


@pytest.mark.django_db
def test_m3u_emits_extinf_and_path_for_downloaded_song():
    _owner, snap = _make_owner_and_snap("P")
    artist = ArtistFactory(name="Daft Punk")
    song = SongFactory(
        primary_artist=artist,
        name="Get Lucky",
        downloaded=True,
    )
    _add_track(snap, song, position=0)

    out = render_m3u(snap)

    assert "#EXTINF:-1,Daft Punk - Get Lucky" in out
    assert song.file_path in out


@pytest.mark.django_db
def test_m3u_skips_song_with_downloaded_false():
    _owner, snap = _make_owner_and_snap("P")
    artist = ArtistFactory(name="Artist")
    # SongFactory with downloaded=False — file_path may still be set from
    # Faker but downloaded=False means we must skip it.
    song = SongFactory(
        primary_artist=artist,
        name="Not Downloaded",
        downloaded=False,
        file_path_ref=None,
    )
    _add_track(snap, song, position=0)

    out = render_m3u(snap)

    assert "#EXTINF" not in out
    assert "Not Downloaded" not in out


@pytest.mark.django_db
def test_m3u_skips_song_with_no_file_path():
    """A song marked downloaded=True but with no file_path_ref is skipped."""
    _owner, snap = _make_owner_and_snap("P")
    from library_manager.models import Artist, Song

    artist = Artist.objects.create(name="Ghost Artist", gid="ghost01")
    song = Song.objects.create(
        name="Phantom Track",
        gid="phantom01",
        primary_artist=artist,
        downloaded=True,
        file_path_ref=None,
    )
    _add_track(snap, song, position=0)

    out = render_m3u(snap)

    assert "#EXTINF" not in out
    assert "Phantom Track" not in out


@pytest.mark.django_db
def test_m3u_tracks_appear_in_position_order():
    _owner, snap = _make_owner_and_snap("P")
    artist = ArtistFactory(name="Artist")
    song_a = SongFactory(primary_artist=artist, name="First", downloaded=True)
    song_b = SongFactory(primary_artist=artist, name="Second", downloaded=True)
    song_c = SongFactory(primary_artist=artist, name="Third", downloaded=True)

    # Insert out of order to confirm ordering is by position, not insertion order
    _add_track(snap, song_c, position=2)
    _add_track(snap, song_a, position=0)
    _add_track(snap, song_b, position=1)

    out = render_m3u(snap)

    idx_first = out.index("First")
    idx_second = out.index("Second")
    idx_third = out.index("Third")
    assert idx_first < idx_second < idx_third


@pytest.mark.django_db
def test_m3u_empty_snapshot_returns_only_header_lines():
    _owner, snap = _make_owner_and_snap("Empty Playlist")
    out = render_m3u(snap)

    assert out.startswith("#EXTM3U\n")
    assert "#EXTINF" not in out
    # Output ends with a newline
    assert out.endswith("\n")


@pytest.mark.django_db
def test_m3u_all_undownloaded_snapshot_returns_only_header_lines():
    _owner, snap = _make_owner_and_snap("All Undownloaded")
    artist = ArtistFactory(name="Ghost")
    for i in range(3):
        song = SongFactory(primary_artist=artist, downloaded=False, file_path_ref=None)
        _add_track(snap, song, position=i)

    out = render_m3u(snap)

    assert out.startswith("#EXTM3U\n")
    assert "#EXTINF" not in out


@pytest.mark.django_db
def test_m3u_output_ends_with_newline():
    _owner, snap = _make_owner_and_snap("P")
    out = render_m3u(snap)
    assert out.endswith("\n")


@pytest.mark.django_db
def test_m3u_mixed_downloaded_and_not():
    """Only downloaded songs with a file path appear as track entries."""
    _owner, snap = _make_owner_and_snap("Mixed")
    artist = ArtistFactory(name="Band")
    downloaded = SongFactory(primary_artist=artist, name="Yes", downloaded=True)
    undownloaded = SongFactory(
        primary_artist=artist, name="No", downloaded=False, file_path_ref=None
    )
    _add_track(snap, downloaded, position=0)
    _add_track(snap, undownloaded, position=1)

    out = render_m3u(snap)

    assert "Yes" in out
    assert "#EXTINF" in out
    lines = out.splitlines()
    extinf_count = sum(1 for line in lines if line.startswith("#EXTINF"))
    assert extinf_count == 1
