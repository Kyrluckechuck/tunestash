import datetime as dt
from unittest.mock import MagicMock, patch

from django.utils import timezone

import pytest
from asgiref.sync import sync_to_async
from tests.factories import ArtistFactory, SongFactory

from queuetip.models import (
    Account,
    ExportSnapshot,
    ExportSnapshotTrack,
    ExternalServiceLink,
    Playlist,
    PlaylistMembership,
)
from queuetip.permissions import PermissionDeniedError
from src.queuetip.errors import NotFoundError
from src.queuetip.services.spotify_export import (
    SpotifyExportError,
    SpotifyExportService,
)


async def _setup_snapshot_with_tracks(track_specs: list[dict]):
    """Returns (account, snapshot). track_specs is e.g. [{"gid": "abc"}, {"gid": ""}]."""
    owner = await sync_to_async(Account.objects.create)(display_name="Jo")
    playlist = await sync_to_async(Playlist.objects.create)(name="P", created_by=owner)
    await sync_to_async(PlaylistMembership.objects.create)(
        playlist=playlist, account=owner, role="owner"
    )
    snapshot = await sync_to_async(ExportSnapshot.objects.create)(
        playlist=playlist, requested_by=owner, rng_seed=1
    )
    artist = await sync_to_async(ArtistFactory)()
    for i, spec in enumerate(track_specs):
        song = await sync_to_async(SongFactory)(primary_artist=artist)
        if "gid" in spec:
            song.gid = spec["gid"]
            await sync_to_async(song.save)()
        await sync_to_async(ExportSnapshotTrack.objects.create)(
            snapshot=snapshot,
            song=song,
            position=i,
            inclusion_reason="rolled_in",
            roll_probability=0.85,
        )
    return owner, snapshot


def _fresh_link(account: Account, expires_in: int = 3600) -> ExternalServiceLink:
    return ExternalServiceLink.objects.create(
        account=account,
        service="spotify",
        access_token="AT",
        refresh_token="RT",
        expires_at=timezone.now() + dt.timedelta(seconds=expires_in),
        scope="x",
        service_user_id="spuser",
    )


def _make_create_resp(playlist_id: str = "pl42") -> MagicMock:
    return MagicMock(
        status_code=201,
        json=lambda: {
            "id": playlist_id,
            "external_urls": {
                "spotify": f"https://open.spotify.com/playlist/{playlist_id}"
            },
        },
        text="",
    )


def _make_add_resp() -> MagicMock:
    return MagicMock(status_code=201, json=lambda: {}, text="")


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_export_happy_path():
    """All 3 tracks have valid gids: added_count=3, skipped_count=0."""
    owner, snapshot = await _setup_snapshot_with_tracks(
        [{"gid": "g1"}, {"gid": "g2"}, {"gid": "g3"}]
    )
    await sync_to_async(_fresh_link)(owner)

    with patch(
        "src.queuetip.services.spotify_export.httpx.post",
        side_effect=[_make_create_resp(), _make_add_resp()],
    ) as mock_post:
        result = await SpotifyExportService.export(owner, snapshot.id)

    assert result.added_count == 3
    assert result.skipped_count == 0
    assert result.skipped_titles == []
    assert result.spotify_playlist_url == "https://open.spotify.com/playlist/pl42"
    assert mock_post.call_count == 2  # create + one batch


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_export_some_tracks_skipped():
    """4 tracks, 1 with empty gid: added=3, skipped=1, skipped_titles contains the song."""
    owner, snapshot = await _setup_snapshot_with_tracks(
        [{"gid": "g1"}, {"gid": "g2"}, {"gid": ""}, {"gid": "g4"}]
    )
    await sync_to_async(_fresh_link)(owner)

    # Retrieve the song with empty gid to check its title in skipped_titles
    tracks = await sync_to_async(
        lambda: list(
            ExportSnapshotTrack.objects.filter(snapshot=snapshot)
            .select_related("song", "song__primary_artist")
            .order_by("position")
        )
    )()
    skipped_song = tracks[2].song

    with patch(
        "src.queuetip.services.spotify_export.httpx.post",
        side_effect=[_make_create_resp(), _make_add_resp()],
    ):
        result = await SpotifyExportService.export(owner, snapshot.id)

    assert result.added_count == 3
    assert result.skipped_count == 1
    assert len(result.skipped_titles) == 1
    assert skipped_song.name in result.skipped_titles[0]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_export_refreshes_expired_token():
    """When expires_at is in the past, refresh_access_token is called and link is updated."""
    owner, snapshot = await _setup_snapshot_with_tracks([{"gid": "g1"}])
    link = await sync_to_async(_fresh_link)(owner, expires_in=-1)  # already expired

    new_tokens = {
        "access_token": "NEW_AT",
        "refresh_token": "NEW_RT",
        "expires_in": "3600",
    }

    with patch(
        "src.queuetip.services.spotify_export.refresh_access_token",
        return_value=new_tokens,
    ):
        with patch(
            "src.queuetip.services.spotify_export.httpx.post",
            side_effect=[_make_create_resp(), _make_add_resp()],
        ):
            result = await SpotifyExportService.export(owner, snapshot.id)

    assert result.added_count == 1

    # Confirm the link row was updated with the new tokens.
    await sync_to_async(link.refresh_from_db)()
    assert link.access_token == "NEW_AT"
    assert link.refresh_token == "NEW_RT"
    assert link.expires_at > timezone.now()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_export_raises_not_found_when_not_linked():
    """No ExternalServiceLink for this account: NotFoundError raised."""
    owner, snapshot = await _setup_snapshot_with_tracks([{"gid": "g1"}])
    # No link created.

    with pytest.raises(NotFoundError):
        await SpotifyExportService.export(owner, snapshot.id)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_export_raises_permission_denied_for_non_member():
    """Caller is not a playlist member: PermissionDeniedError propagates from ExportService."""
    owner, snapshot = await _setup_snapshot_with_tracks([{"gid": "g1"}])
    outsider = await sync_to_async(Account.objects.create)(display_name="X")

    with pytest.raises(PermissionDeniedError):
        await SpotifyExportService.export(outsider, snapshot.id)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_export_raises_spotify_export_error_when_refresh_fails():
    """refresh_access_token raises SpotifyOAuthError → SpotifyExportError is raised."""
    from src.queuetip.spotify_oauth import SpotifyOAuthError

    owner, snapshot = await _setup_snapshot_with_tracks([{"gid": "g1"}])
    await sync_to_async(_fresh_link)(owner, expires_in=-1)  # already expired

    with patch(
        "src.queuetip.services.spotify_export.refresh_access_token",
        side_effect=SpotifyOAuthError("token revoked"),
    ):
        with pytest.raises(SpotifyExportError, match="re-link Spotify"):
            await SpotifyExportService.export(owner, snapshot.id)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_export_raises_spotify_export_error_on_create_failure():
    """Spotify API returns 401 on playlist creation → SpotifyExportError is raised."""
    owner, snapshot = await _setup_snapshot_with_tracks([{"gid": "g1"}])
    await sync_to_async(_fresh_link)(owner)

    error_resp = MagicMock(status_code=401, text="Unauthorized")

    with patch(
        "src.queuetip.services.spotify_export.httpx.post",
        return_value=error_resp,
    ):
        with pytest.raises(
            SpotifyExportError, match="Creating Spotify playlist failed"
        ):
            await SpotifyExportService.export(owner, snapshot.id)
