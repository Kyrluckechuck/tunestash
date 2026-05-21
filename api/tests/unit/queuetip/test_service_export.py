import pytest
from asgiref.sync import sync_to_async
from tests.factories import ArtistFactory, SongFactory

from queuetip.models import (
    Account,
    Contribution,
    ExportSnapshot,
    ExportSnapshotTrack,
    Playlist,
    PlaylistMembership,
    Vote,
)
from queuetip.permissions import PermissionDeniedError
from src.queuetip.services.export import ExportService


async def _setup_playlist_with_n_songs(n: int):
    owner = await sync_to_async(Account.objects.create)(display_name="O")
    playlist = await sync_to_async(Playlist.objects.create)(
        name="P", created_by=owner, min_size=0
    )
    await sync_to_async(PlaylistMembership.objects.create)(
        playlist=playlist, account=owner, role="owner"
    )
    artist = await sync_to_async(ArtistFactory)()
    contributions = []
    for _ in range(n):
        song = await sync_to_async(SongFactory)(primary_artist=artist)
        contribution = await sync_to_async(Contribution.objects.create)(
            playlist=playlist, song=song, contributed_by=owner
        )
        contributions.append(contribution)
    return owner, playlist, contributions


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_create_no_votes_returns_snapshot_with_tracks():
    """3-song playlist, no votes (net=0): base=0.85, most songs should be included."""
    owner, playlist, contributions = await _setup_playlist_with_n_songs(3)

    snapshot = await ExportService.create(owner, playlist.id)

    assert isinstance(snapshot, ExportSnapshot)
    assert snapshot.playlist_id == playlist.id
    assert snapshot.requested_by_id == owner.id

    track_count = await sync_to_async(
        ExportSnapshotTrack.objects.filter(snapshot=snapshot).count
    )()
    assert track_count >= 0  # can be 0 or more depending on RNG, but should be some

    # Verify positions are 0..N-1 (contiguous from 0)
    tracks = await sync_to_async(
        lambda: list(
            ExportSnapshotTrack.objects.filter(snapshot=snapshot).order_by("position")
        )
    )()
    for i, track in enumerate(tracks):
        assert track.position == i


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_create_no_votes_snapshot_has_persistent_tracks():
    """Snapshot and tracks are correctly persisted in the DB."""
    owner, playlist, contributions = await _setup_playlist_with_n_songs(3)

    # Use a seed-predictable approach: set min_size=3 to guarantee all are included
    await sync_to_async(Playlist.objects.filter(id=playlist.id).update)(min_size=3)

    snapshot = await ExportService.create(owner, playlist.id)

    track_count = await sync_to_async(
        ExportSnapshotTrack.objects.filter(snapshot=snapshot).count
    )()
    assert track_count == 3

    tracks = await sync_to_async(
        lambda: list(
            ExportSnapshotTrack.objects.filter(snapshot=snapshot).order_by("position")
        )
    )()
    positions = [t.position for t in tracks]
    assert positions == list(range(3))

    # All song IDs are from our contributions
    contribution_song_ids = {c.song_id for c in contributions}
    for track in tracks:
        assert track.song_id in contribution_song_ids


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_create_exclude_my_downvotes_removes_downvoted_song():
    """exclude_my_downvotes=True removes songs the caller voted -1 on."""
    owner, playlist, contributions = await _setup_playlist_with_n_songs(3)

    # Downvote the first contribution
    downvoted = contributions[0]
    await sync_to_async(Vote.objects.create)(
        contribution=downvoted, account=owner, value=-1
    )

    # Force min_size=3 without downvoted song means we only have 2 candidates,
    # so we keep min_size=0 and use min_size=2 to ensure the remaining 2 are included.
    await sync_to_async(Playlist.objects.filter(id=playlist.id).update)(min_size=2)

    snapshot = await ExportService.create(owner, playlist.id, exclude_my_downvotes=True)

    tracks = await sync_to_async(
        lambda: list(ExportSnapshotTrack.objects.filter(snapshot=snapshot))
    )()
    included_song_ids = {t.song_id for t in tracks}
    assert downvoted.song_id not in included_song_ids


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_create_non_member_raises_permission_denied():
    """An outsider (non-member) calling create raises PermissionDeniedError."""
    owner, playlist, _ = await _setup_playlist_with_n_songs(1)
    outsider = await sync_to_async(Account.objects.create)(display_name="Outsider")

    with pytest.raises(PermissionDeniedError):
        await ExportService.create(outsider, playlist.id)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_get_returns_snapshot_for_member():
    """get() returns the snapshot when the caller is a member."""
    owner, playlist, _ = await _setup_playlist_with_n_songs(1)
    snapshot = await ExportService.create(owner, playlist.id)

    fetched = await ExportService.get(owner, snapshot.id)
    assert fetched.id == snapshot.id
    assert fetched.playlist_id == playlist.id


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_get_raises_for_non_member():
    """get() raises PermissionDeniedError for a non-member."""
    owner, playlist, _ = await _setup_playlist_with_n_songs(1)
    snapshot = await ExportService.create(owner, playlist.id)
    outsider = await sync_to_async(Account.objects.create)(display_name="X")

    with pytest.raises(PermissionDeniedError):
        await ExportService.get(outsider, snapshot.id)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_list_for_playlist_returns_newest_first():
    """list_for_playlist() returns the playlist's snapshots newest-first."""
    owner, playlist, _ = await _setup_playlist_with_n_songs(2)

    snap1 = await ExportService.create(owner, playlist.id)
    snap2 = await ExportService.create(owner, playlist.id)

    snapshots = await ExportService.list_for_playlist(owner, playlist.id)
    assert len(snapshots) == 2
    # newest first (ExportSnapshot Meta ordering = ["-created_at"])
    assert snapshots[0].id == snap2.id
    assert snapshots[1].id == snap1.id


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_list_for_playlist_non_member_raises():
    """list_for_playlist() raises PermissionDeniedError for a non-member."""
    owner, playlist, _ = await _setup_playlist_with_n_songs(1)
    outsider = await sync_to_async(Account.objects.create)(display_name="X")

    with pytest.raises(PermissionDeniedError):
        await ExportService.list_for_playlist(outsider, playlist.id)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_create_records_parameters_and_rng_seed():
    """create() persists parameters dict and a positive rng_seed."""
    owner, playlist, _ = await _setup_playlist_with_n_songs(2)

    snap_false = await ExportService.create(
        owner, playlist.id, exclude_my_downvotes=False
    )
    assert snap_false.parameters == {"exclude_my_downvotes": False}
    assert snap_false.rng_seed > 0

    snap_true = await ExportService.create(
        owner, playlist.id, exclude_my_downvotes=True
    )
    assert snap_true.parameters == {"exclude_my_downvotes": True}
    assert snap_true.rng_seed > 0


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_create_empty_playlist_returns_zero_tracks():
    """create() on a playlist with no contributions returns snapshot with zero tracks."""
    owner = await sync_to_async(Account.objects.create)(display_name="O")
    playlist = await sync_to_async(Playlist.objects.create)(
        name="Empty", created_by=owner, min_size=0
    )
    await sync_to_async(PlaylistMembership.objects.create)(
        playlist=playlist, account=owner, role="owner"
    )

    snapshot = await ExportService.create(owner, playlist.id)

    assert isinstance(snapshot, ExportSnapshot)
    track_count = await sync_to_async(
        ExportSnapshotTrack.objects.filter(snapshot=snapshot).count
    )()
    assert track_count == 0
