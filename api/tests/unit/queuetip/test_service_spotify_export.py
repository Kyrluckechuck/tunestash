"""Tests for SpotifyExportService.sync_target — the playlist-rolled Spotify push.

The snapshot-based export() method was removed; pushing is now driven by a
fresh selection roll over the playlist's current contributions. The roll is
random, so these tests pin it via _RollStub for deterministic assertions.
"""

import datetime as dt
from unittest.mock import MagicMock, patch

from django.utils import timezone

import pytest
from asgiref.sync import sync_to_async
from tests.factories import ArtistFactory, SongFactory

from queuetip.models import (
    Account,
    Contribution,
    ExternalServiceLink,
    Playlist,
    PlaylistExportTarget,
    PlaylistMembership,
)
from src.queuetip.services.spotify_export import (
    EXPIRED_SPOTIFY_SERVICE_USER_ID,
    RemotePlaylistDeletedError,
    SpotifyExportError,
    SpotifyExportService,
)
from src.queuetip.spotify_oauth import SpotifyOAuthError


class _RollStub:
    """Stand-in for roll.RollResult so sync_target tests are deterministic —
    the real roll is random, which would make 'is this song included?'
    assertions flaky."""

    def __init__(self, song_ids: list[int]) -> None:
        self.song_ids = song_ids
        self.warning_message = ""
        self.seed = 1
        self.detail = {}


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


def _make_put_resp(status_code: int = 201) -> MagicMock:
    return MagicMock(status_code=status_code, json=lambda: {}, text="")


def _make_tracks_resp(gids: list[str | None]) -> MagicMock:
    """Mock GET /v1/tracks?ids=... — None means a stale/missing gid."""
    items = [{"id": g, "name": f"Track {g}"} if g is not None else None for g in gids]
    return MagicMock(status_code=200, json=lambda: {"tracks": items}, text="")


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_sync_target_creates_remote_from_current_contributions():
    """Sync-flow Spotify export: rolls the playlist's current contributions
    and creates the Spotify playlist on first push, recording state on the
    unified PlaylistExportTarget."""
    owner = await sync_to_async(Account.objects.create)(display_name="O")
    playlist = await sync_to_async(Playlist.objects.create)(
        name="Auto Mix", created_by=owner
    )
    await sync_to_async(PlaylistMembership.objects.create)(
        playlist=playlist, account=owner, role="owner"
    )
    link = await sync_to_async(_fresh_link)(owner)

    artist = await sync_to_async(ArtistFactory)()
    song = await sync_to_async(SongFactory)(primary_artist=artist)
    song.gid = "G_SYNC"
    await sync_to_async(song.save)()
    await sync_to_async(Contribution.objects.create)(
        playlist=playlist, song=song, contributed_by=owner
    )

    target = await sync_to_async(PlaylistExportTarget.objects.create)(
        account=owner,
        playlist=playlist,
        destination_type=PlaylistExportTarget.DEST_SPOTIFY,
        spotify_link=link,
    )

    with (
        patch(
            "src.queuetip.services.spotify_export.httpx.get",
            return_value=_make_tracks_resp(["G_SYNC"]),
        ),
        patch(
            "src.queuetip.services.spotify_export.httpx.post",
            side_effect=[_make_create_resp(playlist_id="SP_AUTO"), _make_add_resp()],
        ),
        patch("src.queuetip.services.spotify_export._enrich_songs_missing_gids"),
        # The roll is random; pin it to this song so the assertion is stable.
        patch(
            "src.queuetip.services.roll.roll_playlist",
            return_value=_RollStub([song.id]),
        ) as mock_roll,
    ):
        result = await SpotifyExportService.sync_target(target.id)

    assert result.created_new is True
    assert result.added_count == 1
    await sync_to_async(target.refresh_from_db)()
    assert target.remote_playlist_id == "SP_AUTO"
    assert target.last_sync_status == PlaylistExportTarget.STATUS_OK
    assert target.matched_track_count == 1
    mock_roll.assert_called_once_with(
        playlist,
        account=owner,
        exclude_my_downvotes=False,
        min_score_threshold=None,
        target_size_override=None,
        unique_versions_only=False,
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_sync_target_updates_existing_remote_no_duplicate():
    """Second push of a Spotify target must PUT to the existing playlist id —
    no new playlist created (idempotent overwrite)."""
    owner = await sync_to_async(Account.objects.create)(display_name="O")
    playlist = await sync_to_async(Playlist.objects.create)(
        name="Auto Mix", created_by=owner
    )
    await sync_to_async(PlaylistMembership.objects.create)(
        playlist=playlist, account=owner, role="owner"
    )
    link = await sync_to_async(_fresh_link)(owner)

    artist = await sync_to_async(ArtistFactory)()
    song = await sync_to_async(SongFactory)(primary_artist=artist)
    song.gid = "G_AUTO"
    await sync_to_async(song.save)()
    await sync_to_async(Contribution.objects.create)(
        playlist=playlist, song=song, contributed_by=owner
    )

    # Target already has a remote_playlist_id — simulating "second push".
    target = await sync_to_async(PlaylistExportTarget.objects.create)(
        account=owner,
        playlist=playlist,
        destination_type=PlaylistExportTarget.DEST_SPOTIFY,
        spotify_link=link,
        remote_playlist_id="SP_EXISTING",
        last_sync_status=PlaylistExportTarget.STATUS_OK,
    )

    with (
        patch(
            "src.queuetip.services.spotify_export.httpx.get",
            return_value=_make_tracks_resp(["G_AUTO"]),
        ),
        patch(
            "src.queuetip.services.spotify_export.httpx.put",
            return_value=_make_put_resp(),
        ) as mock_put,
        patch("src.queuetip.services.spotify_export.httpx.post") as mock_post,
        patch("src.queuetip.services.spotify_export._enrich_songs_missing_gids"),
        patch(
            "src.queuetip.services.roll.roll_playlist",
            return_value=_RollStub([song.id]),
        ) as mock_roll,
    ):
        result = await SpotifyExportService.sync_target(target.id)

    assert result.created_new is False
    assert "SP_EXISTING" in result.spotify_playlist_url
    assert mock_put.call_count == 1  # PUT to replace tracks
    assert mock_post.call_count == 0  # NO create-playlist call
    mock_roll.assert_called_once_with(
        playlist,
        account=owner,
        exclude_my_downvotes=False,
        min_score_threshold=None,
        target_size_override=None,
        unique_versions_only=False,
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_sync_target_raises_when_remote_deleted_state():
    """Once a target is in STATUS_REMOTE_DELETED, sync_target must refuse —
    user must explicitly recreate (Lifecycle Principle 2)."""
    owner = await sync_to_async(Account.objects.create)(display_name="O")
    playlist = await sync_to_async(Playlist.objects.create)(name="P", created_by=owner)
    await sync_to_async(PlaylistMembership.objects.create)(
        playlist=playlist, account=owner, role="owner"
    )
    link = await sync_to_async(_fresh_link)(owner)
    artist = await sync_to_async(ArtistFactory)()
    song = await sync_to_async(SongFactory)(primary_artist=artist)
    await sync_to_async(Contribution.objects.create)(
        playlist=playlist, song=song, contributed_by=owner
    )

    target = await sync_to_async(PlaylistExportTarget.objects.create)(
        account=owner,
        playlist=playlist,
        destination_type=PlaylistExportTarget.DEST_SPOTIFY,
        spotify_link=link,
        remote_playlist_id="SP_DEAD",
        last_sync_status=PlaylistExportTarget.STATUS_REMOTE_DELETED,
    )

    with pytest.raises(RemotePlaylistDeletedError):
        await SpotifyExportService.sync_target(target.id)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_sync_target_discards_spotify_link_and_notifies_on_invalid_grant():
    owner = await sync_to_async(Account.objects.create)(display_name="O")
    playlist = await sync_to_async(Playlist.objects.create)(name="P", created_by=owner)
    await sync_to_async(PlaylistMembership.objects.create)(
        playlist=playlist, account=owner, role="owner"
    )
    link = await sync_to_async(_fresh_link)(owner, expires_in=-60)
    target = await sync_to_async(PlaylistExportTarget.objects.create)(
        account=owner,
        playlist=playlist,
        destination_type=PlaylistExportTarget.DEST_SPOTIFY,
        spotify_link=link,
    )

    with (
        patch(
            "src.queuetip.services.spotify_export.refresh_access_token",
            side_effect=SpotifyOAuthError(
                "Spotify token refresh failed: 400 invalid_grant"
            ),
        ),
        patch("src.services.notification.NotificationService") as notification_cls,
    ):
        with pytest.raises(SpotifyExportError, match="re-link Spotify"):
            await SpotifyExportService.sync_target(target.id)

    await sync_to_async(link.refresh_from_db)()
    assert link.access_token == ""
    assert link.refresh_token == ""
    assert link.service_user_id == EXPIRED_SPOTIFY_SERVICE_USER_ID
    await sync_to_async(target.refresh_from_db)()
    assert target.last_sync_status == PlaylistExportTarget.STATUS_FAILED
    assert "re-link Spotify" in target.last_error
    notification_cls.return_value.notify_queuetip_spotify_oauth_failed.assert_called_once()
