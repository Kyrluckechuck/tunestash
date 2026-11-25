"""Subsonic creation cleanup when the attempt loses its claim."""

from unittest.mock import MagicMock, patch

import pytest

from library_manager.models import TaskHistory
from queuetip.models import (
    Account,
    Playlist,
    PlaylistExportTarget,
    SubsonicConnection,
)
from queuetip.tasks import ExportGuard
from src.queuetip.export_queue import NONCE_KEY
from src.queuetip.services.subsonic_sync import SubsonicSyncError, sync_subsonic_target


@pytest.mark.django_db(transaction=True)
def test_subsonic_deletion_during_create_deletes_new_remote() -> None:
    owner = Account.objects.create(display_name="Owner")
    playlist = Playlist.objects.create(name="P", created_by=owner)
    connection = SubsonicConnection.objects.create(
        account=owner,
        label="Navidrome",
        server_url="https://music.example.com",
        username="u",
        password_encrypted=b"encrypted",
    )
    target = PlaylistExportTarget.objects.create(
        account=owner,
        playlist=playlist,
        destination_type=PlaylistExportTarget.DEST_SUBSONIC,
        subsonic_connection=connection,
    )
    nonce = "subsonic-create"
    claim = TaskHistory.objects.create(
        task_id="subsonic-guard-test",
        type="SYNC",
        entity_type="PLAYLIST",
        entity_id=str(target.id),
        status="RUNNING",
        log_messages=[{NONCE_KEY: nonce}],
    )
    guard = ExportGuard(claim.pk, target.id, nonce)

    client = MagicMock()
    client.create_playlist.return_value = "remote-456"

    def _create_and_cancel(*_args: object, **_kwargs: object) -> str:
        TaskHistory.objects.filter(pk=claim.pk).update(status="CANCELLED")
        return "remote-456"

    client.create_playlist.side_effect = _create_and_cancel

    with (
        patch(
            "src.queuetip.services.subsonic_sync.decrypt_secret",
            return_value="secret",
        ),
        patch(
            "src.queuetip.services.subsonic_sync.SubsonicClient",
            return_value=client,
        ),
        patch("src.queuetip.services.roll.roll_playlist") as roll,
    ):
        roll.return_value = MagicMock(song_ids=[])
        with pytest.raises(SubsonicSyncError):
            sync_subsonic_target(target.id, guard=guard)

    client.delete_playlist.assert_called_once_with("remote-456")
    target.refresh_from_db()
    assert target.remote_playlist_id == ""
