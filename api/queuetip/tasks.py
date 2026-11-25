"""Celery tasks for Queuetip - bulk collection import and export syncs."""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, Any, cast

from django.db import close_old_connections, transaction
from django.db.models import QuerySet
from django.utils import timezone

from celery import shared_task

from queuetip.models import (
    BulkImportJob,
    Contribution,
    Playlist,
    PlaylistExportTarget,
)
from src.queuetip.resolution.errors import (
    EditorialPlaylistError,
    PlaylistNotFoundError,
    ResolutionError,
    UnsupportedURLError,
)
from src.queuetip.resolution.ingest import ingest_track
from src.queuetip.resolution.playlists import resolve_collection

if TYPE_CHECKING:
    from library_manager.models import TaskHistory

logger = logging.getLogger(__name__)


@shared_task(name="queuetip.tasks.bulk_import_playlist")
def bulk_import_playlist(job_id: int) -> dict[str, Any]:
    """Resolve an album or playlist source and contribute each track."""
    try:
        job = BulkImportJob.objects.select_related("playlist", "requested_by").get(
            id=job_id
        )
    except BulkImportJob.DoesNotExist:
        logger.error("[bulk_import] job %s missing", job_id)
        return {"status": "missing"}

    if job.status in (BulkImportJob.STATUS_SUCCEEDED, BulkImportJob.STATUS_FAILED):
        logger.info(
            "[bulk_import] job %s already in terminal state %s", job_id, job.status
        )
        return {"status": job.status}

    job.status = BulkImportJob.STATUS_RUNNING
    job.save(update_fields=["status"])

    try:
        candidates = resolve_collection(job.source_url)
    except (
        UnsupportedURLError,
        PlaylistNotFoundError,
        EditorialPlaylistError,
    ) as exc:
        job.status = BulkImportJob.STATUS_FAILED
        job.error = str(exc)
        job.finished_at = timezone.now()
        job.save(update_fields=["status", "error", "finished_at"])
        return {"status": "failed", "error": str(exc)}
    except ResolutionError as exc:
        job.status = BulkImportJob.STATUS_FAILED
        job.error = f"Resolution error: {exc}"
        job.finished_at = timezone.now()
        job.save(update_fields=["status", "error", "finished_at"])
        return {"status": "failed", "error": str(exc)}

    job.total_tracks = len(candidates)
    job.save(update_fields=["total_tracks"])

    added = skipped = unresolved = 0
    unresolved_titles: list[str] = []
    playlist: Playlist = cast(Playlist, job.playlist)

    for candidate in candidates:
        try:
            song = ingest_track(candidate)
        except Exception as exc:  # noqa: BLE001 - per-track failures must not abort
            logger.warning(
                "[bulk_import] ingest failed for %s: %s",
                getattr(candidate, "track_name", "?"),
                exc,
            )
            unresolved += 1
            unresolved_titles.append(
                f"{getattr(candidate, 'track_name', '?')} - {getattr(candidate, 'artist_name', '?')}"
            )
        else:
            _, created = Contribution.objects.get_or_create(
                playlist=playlist,
                song=song,
                defaults={"contributed_by": job.requested_by},
            )
            if created:
                added += 1
            else:
                skipped += 1

        job.added_count = added
        job.skipped_count = skipped
        job.unresolved_count = unresolved
        job.unresolved_titles = unresolved_titles
        job.save(
            update_fields=[
                "added_count",
                "skipped_count",
                "unresolved_count",
                "unresolved_titles",
            ]
        )

    job.status = BulkImportJob.STATUS_SUCCEEDED
    job.finished_at = timezone.now()
    job.save(update_fields=["status", "finished_at"])
    return {
        "status": "succeeded",
        "added": added,
        "skipped": skipped,
        "unresolved": unresolved,
    }


class ExportGuard:
    """Fences provider work and target writes to one claimed attempt.

    Every target write and cleanup decision locks target first, then claim,
    in a single transaction. No provider HTTP call happens under these locks.
    """

    def __init__(self, claim_pk: int, target_id: int, nonce: str) -> None:
        self.claim_pk = claim_pk
        self.target_id = target_id
        self.nonce = nonce
        self.stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _claim_filter(self) -> "QuerySet[TaskHistory]":
        from library_manager.models import TaskHistory
        from src.queuetip.export_queue import NONCE_KEY

        return TaskHistory.objects.filter(
            pk=self.claim_pk,
            status="RUNNING",
            log_messages__contains=[{NONCE_KEY: self.nonce}],
        )

    def is_active(self) -> bool:
        return bool(self._claim_filter().exists())

    def touch(self) -> bool:
        """Conditionally refresh the lease heartbeat. False means cancelled."""
        updated = self._claim_filter().update(last_heartbeat=timezone.now())
        if not updated:
            self.stop.set()
        return bool(updated)

    def write_target(self, **fields: Any) -> bool:
        """Fence and write atomically under target -> claim row locks."""
        from queuetip.models import PlaylistExportTarget

        with transaction.atomic():
            target = (
                PlaylistExportTarget.objects.select_for_update()
                .filter(pk=self.target_id)
                .first()
            )
            if target is None:
                return False
            claim = self._claim_filter().select_for_update().first()
            if claim is None:
                return False
            PlaylistExportTarget.objects.filter(pk=target.pk).update(**fields)
            return True

    def should_cleanup_created_remote(self, *, persisted: bool) -> bool:
        """Decide whether a remote created by this attempt may be deleted.

        A never-persisted remote is safe to delete. Once persisted, the ID can
        be adopted by a newer generation; deleting then would destroy a valid
        playlist. Only a deleted target (PK never reused) makes cleanup safe.
        """
        if not persisted:
            return True
        from queuetip.models import PlaylistExportTarget

        with transaction.atomic():
            target = (
                PlaylistExportTarget.objects.select_for_update()
                .filter(pk=self.target_id)
                .first()
            )
            if target is not None:
                return False
            # Target deleted; the remote created by this attempt is orphaned.
            return not self._claim_filter().exists()

    def start_heartbeat(self) -> None:
        def _beat() -> None:
            close_old_connections()
            try:
                while not self.stop.wait(60):
                    self.touch()
            finally:
                close_old_connections()

        self._thread = threading.Thread(
            target=_beat, name=f"export-heartbeat-{self.claim_pk}", daemon=True
        )
        self._thread.start()

    def stop_heartbeat(self) -> None:
        self.stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)


def _adopt_export_claim(target_id: int, nonce: str) -> tuple[Any | None, bool]:
    """Adopt only a pre-existing PENDING claim matching the broker nonce.

    Locks target -> claim so deletion/enqueue cannot interleave.
    """
    from library_manager.models import TaskHistory
    from queuetip.models import PlaylistExportTarget
    from src.queuetip.export_queue import (
        claim_has_nonce,
        claim_is_recreate,
        export_sync_task_id,
    )

    with transaction.atomic():
        target = (
            PlaylistExportTarget.objects.select_for_update()
            .filter(pk=target_id)
            .first()
        )
        if target is None:
            return None, False
        claim = (
            TaskHistory.objects.select_for_update()
            .filter(task_id=export_sync_task_id(target_id))
            .first()
        )
        if (
            claim is None
            or claim.status != "PENDING"
            or not claim_has_nonce(claim, nonce)
        ):
            logger.info(
                "[export-sync] no matching PENDING claim for target %s nonce %s",
                target_id,
                nonce,
            )
            return None, False
        recreate = claim_is_recreate(claim, nonce)
        now = timezone.now()
        claim.status = "RUNNING"
        claim.started_at = now
        claim.last_heartbeat = now
        claim.save(update_fields=["status", "started_at", "last_heartbeat"])
        return claim, recreate


def _run_export_sync(target: PlaylistExportTarget, guard: ExportGuard) -> None:
    """Dispatch to the provider service that matches the target."""
    if target.destination_type == PlaylistExportTarget.DEST_SUBSONIC:
        from src.queuetip.services.subsonic_sync import sync_subsonic_target

        sync_subsonic_target(target.id, guard=guard)
        return
    if target.destination_type == PlaylistExportTarget.DEST_SPOTIFY:
        from asgiref.sync import async_to_sync

        from src.queuetip.services.spotify_export import SpotifyExportService

        async_to_sync(SpotifyExportService.sync_target)(target.id, guard=guard)
        return
    raise ValueError(f"Unknown destination_type: {target.destination_type}")


@shared_task(
    bind=True,
    name="queuetip.tasks.sync_export_target",
    queue="queuetip",
    soft_time_limit=25 * 60,
    time_limit=28 * 60,
)
def sync_export_target(self: Any, target_id: int, nonce: str) -> dict[str, str]:
    """Run one export sync; only a matching pre-existing claim may execute."""
    from library_manager.models import TaskHistory
    from library_manager.tasks.core import check_task_cancellation, complete_task
    from queuetip.models import PlaylistExportTarget

    task_id = str(self.request.id)
    try:
        target = PlaylistExportTarget.objects.select_related(
            "account", "playlist", "spotify_link", "subsonic_connection"
        ).get(id=int(target_id))
    except PlaylistExportTarget.DoesNotExist:
        logger.error("[export-sync] target %s missing", target_id)
        TaskHistory.objects.filter(
            task_id=task_id, status__in=TaskHistory.ACTIVE_STATUSES
        ).update(status="CANCELLED", completed_at=timezone.now())
        return {"status": "missing"}

    claim, recreate = _adopt_export_claim(target.id, nonce)
    if claim is None:
        return {"status": "duplicate"}

    guard = ExportGuard(claim.pk, target.id, nonce)
    try:
        if check_task_cancellation(claim):
            return {"status": "cancelled"}

        if (
            not recreate
            and target.last_sync_status == PlaylistExportTarget.STATUS_REMOTE_DELETED
        ):
            complete_task(
                claim,
                success=False,
                error_message=(
                    "Remote playlist was deleted. Recreate it from the queuetip UI."
                ),
            )
            return {"status": "remote_deleted"}

        fields: dict[str, Any] = {
            "last_sync_status": PlaylistExportTarget.STATUS_PENDING,
            "last_error": "",
        }
        if recreate:
            fields["remote_playlist_id"] = ""
        if not guard.write_target(**fields):
            complete_task(
                claim, success=False, error_message="Sync target was removed."
            )
            return {"status": "missing"}

        if check_task_cancellation(claim):
            return {"status": "cancelled"}

        guard.start_heartbeat()
        try:
            _run_export_sync(target, guard)
        finally:
            guard.stop_heartbeat()

        if not guard.is_active():
            return {"status": "cancelled"}
        complete_task(claim, success=True)
        return {"status": "completed"}
    except Exception as exc:  # noqa: BLE001 - claim must always be finalized
        logger.exception("[export-sync] target %s failed", target_id)
        if not guard.is_active():
            return {"status": "cancelled"}
        complete_task(claim, success=False, error_message=str(exc))
        return {"status": "failed", "error": str(exc)}
