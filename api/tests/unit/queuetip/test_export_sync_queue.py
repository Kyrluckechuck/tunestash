"""QueueTip export sync queue/task lifecycle tests."""

from unittest.mock import patch

from django.utils import timezone

import pytest

from library_manager.models import TaskHistory
from queuetip.models import (
    Account,
    ExternalServiceLink,
    Playlist,
    PlaylistExportTarget,
    PlaylistMembership,
)
from queuetip.tasks import ExportGuard, sync_export_target
from src.queuetip.errors import NotFoundError, ValidationError
from src.queuetip.export_queue import (
    NONCE_KEY,
    enqueue_export_sync,
    export_sync_task_id,
    is_export_sync_active,
)
from src.queuetip.schema.mutation import _queue_export_target


def _owner() -> Account:
    return Account.objects.create(display_name="Owner")


def _playlist(owner: Account) -> Playlist:
    playlist = Playlist.objects.create(name="Test Playlist", created_by=owner)
    PlaylistMembership.objects.create(
        account=owner, playlist=playlist, role=PlaylistMembership.ROLE_OWNER
    )
    return playlist


def _spotify_link(account: Account) -> ExternalServiceLink:
    return ExternalServiceLink.objects.create(
        account=account,
        service=ExternalServiceLink.SERVICE_SPOTIFY,
        service_user_id="spotify-user",
        access_token="encrypted-access",
        refresh_token="encrypted-refresh",
        expires_at=timezone.now().replace(year=2099),
        scope="playlist-modify-private",
    )


def _spotify_target(owner: Account, playlist: Playlist) -> PlaylistExportTarget:
    return PlaylistExportTarget.objects.create(
        account=owner,
        playlist=playlist,
        destination_type=PlaylistExportTarget.DEST_SPOTIFY,
        spotify_link=_spotify_link(owner),
        remote_playlist_id="old-remote",
    )


def _claim(target_id: int, nonce: str, status: str = "PENDING") -> TaskHistory:
    return TaskHistory.objects.create(
        task_id=export_sync_task_id(target_id),
        type="SYNC",
        entity_type="PLAYLIST",
        entity_id=str(target_id),
        status=status,
        log_messages=[{NONCE_KEY: nonce}],
    )


@pytest.mark.django_db(transaction=True)
def test_enqueue_publishes_target_and_nonce_only_and_dedupes() -> None:
    owner = _owner()
    target = _spotify_target(owner, _playlist(owner))

    with patch("queuetip.tasks.sync_export_target.apply_async") as publish:
        assert enqueue_export_sync(target) is True
        assert enqueue_export_sync(target) is False

    publish.assert_called_once()
    args = publish.call_args.kwargs["args"]
    assert len(args) == 2 and args[0] == target.id
    nonce = args[1]
    assert publish.call_args.kwargs["task_id"] == export_sync_task_id(target.id)
    assert is_export_sync_active(target.id) is True

    claim = TaskHistory.objects.get(task_id=export_sync_task_id(target.id))
    assert claim.status == "PENDING"
    assert any(entry.get(NONCE_KEY) == nonce for entry in claim.log_messages)


@pytest.mark.django_db(transaction=True)
def test_task_adopts_matching_claim_and_completes() -> None:
    owner = _owner()
    target = _spotify_target(owner, _playlist(owner))
    nonce = "attempt-1"
    _claim(target.id, nonce)

    with patch("queuetip.tasks._run_export_sync") as run:
        result = sync_export_target.apply(
            args=[target.id, nonce], task_id=export_sync_task_id(target.id)
        ).get()

    assert result["status"] == "completed"
    run.assert_called_once()
    assert (
        TaskHistory.objects.get(task_id=export_sync_task_id(target.id)).status
        == "COMPLETED"
    )


@pytest.mark.django_db(transaction=True)
def test_stale_redelivery_with_no_claim_is_rejected() -> None:
    owner = _owner()
    target = _spotify_target(owner, _playlist(owner))

    with patch("queuetip.tasks._run_export_sync") as run:
        result = sync_export_target.apply(
            args=[target.id, "stale-nonce"], task_id=export_sync_task_id(target.id)
        ).get()

    assert result["status"] == "duplicate"
    run.assert_not_called()
    assert not TaskHistory.objects.filter(
        task_id=export_sync_task_id(target.id)
    ).exists()


@pytest.mark.django_db(transaction=True)
def test_old_nonce_cannot_adopt_newer_pending_claim() -> None:
    owner = _owner()
    target = _spotify_target(owner, _playlist(owner))
    _claim(target.id, "new-nonce")

    with patch("queuetip.tasks._run_export_sync") as run:
        result = sync_export_target.apply(
            args=[target.id, "old-nonce"], task_id=export_sync_task_id(target.id)
        ).get()

    assert result["status"] == "duplicate"
    run.assert_not_called()
    claim = TaskHistory.objects.get(task_id=export_sync_task_id(target.id))
    assert claim.status == "PENDING"
    assert claim.log_messages[0][NONCE_KEY] == "new-nonce"


@pytest.mark.django_db(transaction=True)
def test_duplicate_delivery_of_running_claim_does_not_run_provider() -> None:
    owner = _owner()
    target = _spotify_target(owner, _playlist(owner))
    _claim(target.id, "attempt-1", status="RUNNING")

    with patch("queuetip.tasks._run_export_sync") as run:
        result = sync_export_target.apply(
            args=[target.id, "attempt-1"], task_id=export_sync_task_id(target.id)
        ).get()

    assert result["status"] == "duplicate"
    run.assert_not_called()


@pytest.mark.django_db(transaction=True)
def test_missing_target_finalizes_claim_without_provider() -> None:
    with patch("queuetip.tasks._run_export_sync") as run:
        result = sync_export_target.apply(
            args=[9999, "attempt-1"], task_id=export_sync_task_id(9999)
        ).get()

    assert result["status"] == "missing"
    run.assert_not_called()


@pytest.mark.django_db(transaction=True)
def test_recreate_does_not_clear_remote_id_on_publish_failure() -> None:
    owner = _owner()
    target = _spotify_target(owner, _playlist(owner))

    with patch(
        "src.queuetip.export_queue.enqueue_export_sync",
        side_effect=RuntimeError("broker"),
    ):
        with pytest.raises(RuntimeError):
            _queue_export_target(owner, target.id, recreate=True)

    target.refresh_from_db()
    assert target.remote_playlist_id == "old-remote"


@pytest.mark.django_db(transaction=True)
def test_recreate_claim_clears_remote_id_only_in_worker() -> None:
    owner = _owner()
    target = _spotify_target(owner, _playlist(owner))
    nonce = "recreate-attempt"
    claim = _claim(target.id, nonce)
    claim.log_messages[0]["export_sync_recreate"] = True
    claim.save(update_fields=["log_messages"])

    with patch("queuetip.tasks._run_export_sync"):
        result = sync_export_target.apply(
            args=[target.id, nonce], task_id=export_sync_task_id(target.id)
        ).get()

    assert result["status"] == "completed"
    target.refresh_from_db()
    assert target.remote_playlist_id == ""


@pytest.mark.django_db(transaction=True)
def test_recreate_rejected_while_sync_claim_active() -> None:
    owner = _owner()
    target = _spotify_target(owner, _playlist(owner))
    _claim(target.id, "attempt-1")

    with pytest.raises(ValidationError):
        _queue_export_target(owner, target.id, recreate=True)

    target.refresh_from_db()
    assert target.remote_playlist_id == "old-remote"


@pytest.mark.django_db(transaction=True)
def test_queue_rejects_cross_account_target() -> None:
    owner = _owner()
    other = _owner()
    target = _spotify_target(owner, _playlist(owner))

    with pytest.raises(NotFoundError):
        _queue_export_target(other, target.id, recreate=False)


@pytest.mark.django_db(transaction=True)
def test_guard_heartbeat_advances_claim_and_survives_false_stuck_window() -> None:
    owner = _owner()
    target = _spotify_target(owner, _playlist(owner))
    claim = _claim(target.id, "heartbeat")
    claim.status = "RUNNING"
    claim.save(update_fields=["status"])
    old = timezone.now() - timezone.timedelta(minutes=11)
    TaskHistory.objects.filter(pk=claim.pk).update(started_at=old, last_heartbeat=old)
    claim.refresh_from_db()
    assert claim.is_stuck() is True

    guard = ExportGuard(claim.pk, target.id, "heartbeat")
    assert guard.touch() is True
    claim.refresh_from_db()
    assert claim.is_stuck() is False


@pytest.mark.django_db(transaction=True)
def test_cancelled_claim_blocks_guard_writes_and_heartbeat() -> None:
    owner = _owner()
    target = _spotify_target(owner, _playlist(owner))
    claim = _claim(target.id, "cancelled")
    claim.status = "RUNNING"
    claim.save(update_fields=["status"])
    guard = ExportGuard(claim.pk, target.id, "cancelled")

    TaskHistory.objects.filter(pk=claim.pk).update(status="CANCELLED")

    assert guard.is_active() is False
    assert guard.touch() is False
    assert guard.write_target(last_error="stale") is False
    target.refresh_from_db()
    assert target.last_error == ""

    # A newer generation cannot be written by the old guard either.
    TaskHistory.objects.filter(pk=claim.pk).update(
        status="RUNNING", log_messages=[{NONCE_KEY: "new-generation"}]
    )
    assert guard.write_target(last_error="stale") is False
