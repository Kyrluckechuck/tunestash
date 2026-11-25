"""Concurrency interleaving regressions for the export generation fence."""

import threading
import time
from unittest.mock import patch

from django.db import connection, transaction
from django.utils import timezone

import pytest

from library_manager.models import TaskHistory
from queuetip.models import (
    Account,
    ExternalServiceLink,
    Playlist,
    PlaylistExportTarget,
)
from queuetip.tasks import ExportGuard, _adopt_export_claim
from src.queuetip.export_queue import (
    NONCE_KEY,
    RECREATE_KEY,
    claim_is_recreate,
    enqueue_export_sync,
    export_sync_task_id,
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


def _claim(target_id: int, nonce: str, status: str = "RUNNING") -> TaskHistory:
    return TaskHistory.objects.create(
        task_id=export_sync_task_id(target_id),
        type="SYNC",
        entity_type="PLAYLIST",
        entity_id=str(target_id),
        status=status,
        log_messages=[{NONCE_KEY: nonce}],
    )


@pytest.mark.django_db(transaction=True)
def test_claim_metadata_is_atomic_before_publish() -> None:
    target = _target()
    observed: list[list[dict]] = []

    def _inspect(**_kwargs: object) -> None:
        connection.close_if_unusable_or_obsolete()
        claim = TaskHistory.objects.get(task_id=export_sync_task_id(target.id))
        observed.append(list(claim.log_messages))

    with patch(
        "queuetip.tasks.sync_export_target.apply_async", side_effect=_inspect
    ) as publish:
        assert enqueue_export_sync(target) is True

    publish.assert_called_once()
    assert observed[0][0][NONCE_KEY]
    assert RECREATE_KEY not in observed[0][0]


@pytest.mark.django_db(transaction=True)
def test_claim_metadata_recreate_bound_to_matching_nonce() -> None:
    target = _target()
    claim = _claim(target.id, "new")
    claim.log_messages = [
        {NONCE_KEY: "new"},
        {NONCE_KEY: "old", RECREATE_KEY: True},
    ]
    claim.save(update_fields=["log_messages"])
    assert claim_is_recreate(claim, "new") is False
    assert claim_is_recreate(claim, "old") is True

    TaskHistory.objects.filter(pk=claim.pk).update(status="PENDING")
    adopted, recreate = _adopt_export_claim(target.id, "new")
    assert adopted is not None
    assert recreate is False


@pytest.mark.django_db(transaction=True)
def test_cancellation_while_claim_locked_blocks_stale_target_write() -> None:
    target = _target()
    claim = _claim(target.id, "old")
    guard = ExportGuard(claim.pk, target.id, "old")
    started = threading.Event()

    def _cancel_holding_lock() -> None:
        with transaction.atomic():
            locked = TaskHistory.objects.select_for_update().get(pk=claim.pk)
            locked.status = "CANCELLED"
            locked.save(update_fields=["status"])
            started.set()
            time.sleep(0.5)

    canceller = threading.Thread(target=_cancel_holding_lock)
    canceller.start()
    assert started.wait(3)

    # The writer waits on the same claim row, then sees CANCELLED.
    assert guard.write_target(last_error="stale") is False
    canceller.join(timeout=3)
    target.refresh_from_db()
    assert target.last_error == ""


@pytest.mark.django_db(transaction=True)
def test_persisted_remote_is_not_cleaned_up_after_newer_generation_adopts_it() -> None:
    target = _target()
    claim = _claim(target.id, "old")
    guard = ExportGuard(claim.pk, target.id, "old")
    TaskHistory.objects.filter(pk=claim.pk).update(status="CANCELLED")

    # Target still exists: a newer generation may be using the persisted ID.
    assert guard.should_cleanup_created_remote(persisted=True) is False
    target.delete()
    # After target deletion the PK is never reused; cleanup is safe.
    assert guard.should_cleanup_created_remote(persisted=True) is True


@pytest.mark.django_db(transaction=True)
def test_never_persisted_remote_is_cleaned_up_on_guard_loss() -> None:
    target = _target()
    claim = _claim(target.id, "old")
    guard = ExportGuard(claim.pk, target.id, "old")
    assert guard.should_cleanup_created_remote(persisted=False) is True
    target.delete()
    assert guard.should_cleanup_created_remote(persisted=False) is True
