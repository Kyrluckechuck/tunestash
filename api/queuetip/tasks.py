"""Celery tasks for Queuetip — bulk playlist import + Subsonic sync."""

from __future__ import annotations

import logging
import time
from typing import Any, cast

from django.utils import timezone

from celery import shared_task

from queuetip.models import BulkImportJob, Contribution, Playlist, PlaylistExportTarget
from src.queuetip.resolution.errors import (
    EditorialPlaylistError,
    PlaylistNotFoundError,
    ResolutionError,
    UnsupportedURLError,
)
from src.queuetip.resolution.ingest import ingest_track
from src.queuetip.resolution.playlists import resolve_playlist

logger = logging.getLogger(__name__)

# Auto-sync debounce window. All Contribution / Vote mutations within the
# same 60s window for a given target coalesce to one sync task (the task ID
# is derived from `(target_id, floor(now/AUTO_SYNC_DEBOUNCE_SECS))`).
AUTO_SYNC_DEBOUNCE_SECS = 60


@shared_task(name="queuetip.tasks.bulk_import_playlist")
def bulk_import_playlist(job_id: int) -> dict[str, Any]:
    """Resolve a playlist URL and create Contributions for each track.

    - Idempotent skip on tracks already contributed to the playlist.
    - Unresolvable tracks are recorded by title in `unresolved_titles`.
    - A bad/non-public URL fails the whole job with `status=failed`.
    - Per-track failures do NOT abort the run.
    - Re-running a job in a terminal state is a no-op.
    """
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
        candidates = resolve_playlist(job.source_url)
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

    # Surface total so the UI can show "X / Y processed" while the task runs.
    # Saved before the first ingest so the polling client sees it on the next
    # tick instead of staying at null for the duration.
    job.total_tracks = len(candidates)
    job.save(update_fields=["total_tracks"])

    added = skipped = unresolved = 0
    unresolved_titles: list[str] = []
    playlist: Playlist = cast(Playlist, job.playlist)

    for candidate in candidates:
        try:
            song = ingest_track(candidate)
        except Exception as exc:  # noqa: BLE001 — per-track failures must not abort
            logger.warning(
                "[bulk_import] ingest failed for %s: %s",
                getattr(candidate, "track_name", "?"),
                exc,
            )
            unresolved += 1
            unresolved_titles.append(
                f"{getattr(candidate, 'track_name', '?')} — "
                f"{getattr(candidate, 'artist_name', '?')}"
            )
        else:
            if Contribution.objects.filter(playlist=playlist, song=song).exists():
                skipped += 1
            else:
                Contribution.objects.create(
                    playlist=playlist, song=song, contributed_by=job.requested_by
                )
                added += 1

        # Live progress for the polling UI. One row update per track is fine —
        # bulk-import playlists are bounded (Spotify caps at 10k, typical use
        # <500) and the polling cadence is 2s so contention is non-existent.
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


@shared_task(name="queuetip.tasks.sync_export_target", bind=True, max_retries=2)
def sync_export_target(self, target_id: int) -> dict[str, Any]:
    """Push a queuetip playlist's current state to its remote target.

    Dispatches on `destination_type`. Used for both manual ('sync now')
    triggers and the 60s-debounced auto-sync.

    Failures are recorded on the target row (last_sync_status, last_error)
    and re-raised so Celery's retry mechanism can apply for transient
    network errors. Permanent errors (auth, remote_deleted) skip retry.
    """
    try:
        target = PlaylistExportTarget.objects.get(id=target_id)
    except PlaylistExportTarget.DoesNotExist:
        logger.warning("[sync_export_target] target %s missing", target_id)
        return {"status": "missing"}

    if target.destination_type == PlaylistExportTarget.DEST_SUBSONIC:
        from src.queuetip.services.subsonic_sync import (
            SubsonicSyncError,
            sync_subsonic_target,
        )

        try:
            result = sync_subsonic_target(target_id)
        except SubsonicSyncError as exc:
            # Permanent — already recorded on the target by the service.
            logger.info("[sync_export_target] subsonic %s: %s", target_id, exc)
            return {"status": "failed", "error": str(exc)}
        return {
            "status": "ok",
            "matched": result.matched_count,
            "total": result.total_count,
            "unmatched": len(result.unmatched_titles),
            "queued_downloads": result.queued_downloads,
        }

    # Spotify path: today's sync still goes through the existing
    # SpotifyExportService entry point (snapshot-based). A follow-up will
    # add a target-based wrapper so this task can drive Spotify too.
    logger.warning(
        "[sync_export_target] destination_type=%s not yet driven by Celery (target=%s)",
        target.destination_type,
        target_id,
    )
    return {"status": "skipped", "reason": "destination_not_yet_celery_driven"}


def schedule_auto_sync_for_playlist(playlist_id: int) -> None:
    """Find every PlaylistExportTarget on this playlist with sync_mode=on_change
    and queue a debounced sync 60s out.

    Called from Contribution/Vote post-save signals. Idempotent within a 60s
    window — the task ID is derived from `(target_id, floor(now/60))`, so
    repeated calls within the same window produce the same task ID and
    Celery's broker (Valkey) deduplicates.

    Skips targets in STATUS_REMOTE_DELETED — automation must not silently
    fight against an explicit user deletion (Lifecycle Principle 2).
    """
    window = int(time.time() // AUTO_SYNC_DEBOUNCE_SECS)
    qs = PlaylistExportTarget.objects.filter(
        playlist_id=playlist_id,
        sync_mode=PlaylistExportTarget.SYNC_ON_CHANGE,
    ).exclude(last_sync_status=PlaylistExportTarget.STATUS_REMOTE_DELETED)

    for target in qs.only("id"):
        task_id = f"queuetip-auto-sync-{target.id}-{window}"
        try:
            sync_export_target.apply_async(
                args=[target.id],
                task_id=task_id,
                countdown=AUTO_SYNC_DEBOUNCE_SECS,
            )
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning(
                "[auto-sync] could not queue sync for target %s: %s",
                target.id,
                exc,
            )


@shared_task(name="queuetip.tasks.requeue_stale_export_targets")
def requeue_stale_export_targets() -> dict[str, Any]:
    """Periodic catch-up: re-sync auto-sync targets that have unmatched tracks.

    Pairs with `_maybe_queue_download` in the Subsonic sync service: when a
    sync run can't find a track on the remote, queuetip queues a TuneStash
    download. The download eventually appears in the user's Navidrome.
    Without this task, the user would have to click 'Sync now' to see the
    newly-available track in their playlist. With it, the next periodic
    tick (every 15min via Celery Beat) re-runs the sync, picks up the
    formerly-unmatched track, and the unmatched_track_titles list shrinks.

    Once a target's unmatched list is empty, it falls out of the candidate
    set and stops getting periodically re-synced — back to event-driven.

    REMOTE_DELETED targets are excluded; they require explicit re-link.
    """
    targets = (
        PlaylistExportTarget.objects.filter(
            sync_mode=PlaylistExportTarget.SYNC_ON_CHANGE,
        )
        .exclude(unmatched_track_titles=[])
        .exclude(last_sync_status=PlaylistExportTarget.STATUS_REMOTE_DELETED)
    )
    count = 0
    for t in targets.only("id"):
        sync_export_target.delay(t.id)
        count += 1
    if count:
        logger.info("[requeue_stale] queued %s stale export targets", count)
    return {"queued": count}
