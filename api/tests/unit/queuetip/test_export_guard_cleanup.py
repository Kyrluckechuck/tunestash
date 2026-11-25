"""Generation guard cleanup tests for export provider services."""

from unittest.mock import patch

from django.utils import timezone

import pytest
from asgiref.sync import sync_to_async

from library_manager.models import TaskHistory
from queuetip.models import (
    Account,
    ExternalServiceLink,
    Playlist,
    PlaylistExportTarget,
)
from queuetip.tasks import ExportGuard
from src.queuetip.export_queue import NONCE_KEY
from src.queuetip.services.spotify_export import (
    SpotifyExportError,
    SpotifyExportService,
)


def _target() -> PlaylistExportTarget:
    owner = Account.objects.create(display_name="Owner")
    playlist = Playlist.objects.create(name="P", created_by=owner)
    link = ExternalServiceLink.objects.create(
        account=owner,
        service=ExternalServiceLink.SERVICE_SPOTIFY,
        service_user_id="u",
        access_token="a",
        refresh_token="r",
        expires_at=timezone.now().replace(year=2099),
        scope="playlist-modify-private",
    )
    return PlaylistExportTarget.objects.create(
        account=owner,
        playlist=playlist,
        destination_type=PlaylistExportTarget.DEST_SPOTIFY,
        spotify_link=link,
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_spotify_deletion_during_create_deletes_new_remote() -> None:
    target = await sync_to_async(_target)()
    nonce = "create-attempt"
    claim = await sync_to_async(TaskHistory.objects.create)(
        task_id="export-guard-test",
        type="SYNC",
        entity_type="PLAYLIST",
        entity_id=str(target.id),
        status="RUNNING",
        log_messages=[{NONCE_KEY: nonce}],
    )
    guard = ExportGuard(claim.pk, target.id, nonce)

    def _create_and_cancel(*_args: object, **_kwargs: object) -> tuple[str, str]:
        # Deletion/cancellation happens while the create HTTP call is in flight.
        TaskHistory.objects.filter(pk=claim.pk).update(status="CANCELLED")
        return "https://open.spotify.com/playlist/remote-123", "remote-123"

    with (
        patch(
            "src.queuetip.services.spotify_export._ensure_fresh_token",
            return_value="token",
        ),
        patch(
            "src.queuetip.services.spotify_export._enrich_songs_missing_gids",
            return_value=None,
        ),
        patch(
            "src.queuetip.services.spotify_export._collect_song_candidates",
            return_value=([], []),
        ),
        patch(
            "src.queuetip.services.spotify_export._validate_and_collect_uris",
            return_value=([], []),
        ),
        patch(
            "src.queuetip.services.spotify_export._create_playlist",
            side_effect=_create_and_cancel,
        ),
        patch(
            "src.queuetip.services.spotify_export._best_effort_delete_remote"
        ) as delete_remote,
    ):
        with pytest.raises(SpotifyExportError):
            await SpotifyExportService.sync_target(target.id, guard=guard)

    delete_remote.assert_called_once()
    assert delete_remote.call_args.args[1] == "remote-123"
    await sync_to_async(target.refresh_from_db)()
    assert target.remote_playlist_id == ""
