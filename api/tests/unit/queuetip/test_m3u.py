"""Tests for queuetip m3u export rendering.

The m3u format now embeds Subsonic stream URLs from the requesting user's
configured Subsonic connection — local file paths are no longer emitted.
These tests mock the Subsonic client's track resolution rather than hitting
a real server.
"""

from unittest.mock import patch

import pytest
from tests.factories import ArtistFactory, SongFactory

from queuetip.models import (
    Account,
    ExportSnapshot,
    ExportSnapshotTrack,
    Playlist,
    SubsonicConnection,
)
from src.queuetip.crypto import encrypt_secret
from src.queuetip.m3u import M3uExportError, render_m3u


def _make_owner_and_snap(playlist_name: str = "Test Playlist", rng_seed: int = 1):
    owner = Account.objects.create(display_name="O")
    playlist = Playlist.objects.create(name=playlist_name, created_by=owner)
    snap = ExportSnapshot.objects.create(
        playlist=playlist, requested_by=owner, rng_seed=rng_seed
    )
    return owner, snap


def _connect(owner: Account, *, label: str = "Home Navidrome") -> SubsonicConnection:
    return SubsonicConnection.objects.create(
        account=owner,
        label=label,
        server_url="https://navi.example.com",
        username="alice",
        password_encrypted=encrypt_secret("hunter2"),
    )


def _add_track(snap, song, position, reason="rolled_in", probability=0.85):
    return ExportSnapshotTrack.objects.create(
        snapshot=snap,
        song=song,
        position=position,
        inclusion_reason=reason,
        roll_probability=probability,
    )


@pytest.mark.django_db
def test_m3u_raises_when_no_subsonic_connection():
    """The new m3u flow requires a Subsonic connection — without one we can't
    build stream URLs. Fail loudly so the user gets a clear instruction."""
    _owner, snap = _make_owner_and_snap()
    with pytest.raises(M3uExportError, match="Connect a Subsonic server"):
        render_m3u(snap)


@pytest.mark.django_db
def test_m3u_starts_with_extm3u_header():
    owner, snap = _make_owner_and_snap("Friday Mix")
    _connect(owner)
    with patch("src.queuetip.m3u.resolve_song_to_subsonic_id", return_value=None):
        out = render_m3u(snap)
    assert out.startswith("#EXTM3U\n")


@pytest.mark.django_db
def test_m3u_header_includes_playlist_name_and_snapshot_id():
    owner, snap = _make_owner_and_snap("Friday Mix")
    _connect(owner)
    with patch("src.queuetip.m3u.resolve_song_to_subsonic_id", return_value=None):
        out = render_m3u(snap)
    assert "Friday Mix" in out
    assert f"snapshot {snap.id}" in out


@pytest.mark.django_db
def test_m3u_emits_extinf_and_stream_url_for_resolved_song():
    owner, snap = _make_owner_and_snap("P")
    _connect(owner)
    artist = ArtistFactory(name="Daft Punk")
    song = SongFactory(primary_artist=artist, name="Get Lucky")
    _add_track(snap, song, position=0)

    with patch("src.queuetip.m3u.resolve_song_to_subsonic_id", return_value="ns-42"):
        out = render_m3u(snap)

    assert "#EXTINF:-1,Daft Punk - Get Lucky" in out
    # The stream URL points at the user's server with the resolved track id.
    assert "https://navi.example.com/rest/stream.view?" in out
    assert "id=ns-42" in out
    # Auth params are present.
    assert "u=alice" in out
    assert "t=" in out
    assert "s=" in out


@pytest.mark.django_db
def test_m3u_unmatched_song_emitted_as_comment_not_dropped():
    """A track that doesn't resolve on the user's Subsonic shouldn't disappear
    from the file silently — the user should see what's missing."""
    owner, snap = _make_owner_and_snap("P")
    _connect(owner)
    artist = ArtistFactory(name="Some Artist")
    song = SongFactory(primary_artist=artist, name="Obscure Track")
    _add_track(snap, song, position=0)

    with patch("src.queuetip.m3u.resolve_song_to_subsonic_id", return_value=None):
        out = render_m3u(snap)

    assert "# unmatched: Some Artist - Obscure Track" in out
    # No stream URL is emitted for an unmatched track.
    assert "rest/stream.view" not in out


@pytest.mark.django_db
def test_m3u_tracks_appear_in_position_order():
    owner, snap = _make_owner_and_snap("P")
    _connect(owner)
    artist = ArtistFactory()
    s1 = SongFactory(primary_artist=artist, name="First")
    s2 = SongFactory(primary_artist=artist, name="Second")
    s3 = SongFactory(primary_artist=artist, name="Third")
    _add_track(snap, s2, position=1)
    _add_track(snap, s3, position=2)
    _add_track(snap, s1, position=0)

    def fake_resolve(*, title, artist, isrc, client):
        return {"First": "id-1", "Second": "id-2", "Third": "id-3"}[title]

    with patch(
        "src.queuetip.m3u.resolve_song_to_subsonic_id", side_effect=fake_resolve
    ):
        out = render_m3u(snap)

    lines = out.splitlines()
    # Stream URLs ordered as expected (id-1 before id-2 before id-3).
    pos1 = next(i for i, l in enumerate(lines) if "id=id-1" in l)
    pos2 = next(i for i, l in enumerate(lines) if "id=id-2" in l)
    pos3 = next(i for i, l in enumerate(lines) if "id=id-3" in l)
    assert pos1 < pos2 < pos3


@pytest.mark.django_db
def test_m3u_empty_snapshot_returns_only_header_lines():
    owner, snap = _make_owner_and_snap("Empty")
    _connect(owner)
    out = render_m3u(snap)
    lines = [line for line in out.splitlines() if line.strip()]
    # Header + comment + Stream-URLs-from-... comment. No track entries.
    assert lines[0] == "#EXTM3U"
    assert any("Stream URLs from" in line for line in lines)
    assert not any(line.startswith("#EXTINF") for line in lines)


@pytest.mark.django_db
def test_m3u_output_ends_with_newline():
    owner, snap = _make_owner_and_snap("P")
    _connect(owner)
    out = render_m3u(snap)
    assert out.endswith("\n")
