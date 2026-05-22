"""Celery tasks for Queuetip — bulk playlist import."""

from __future__ import annotations

import logging
from typing import Any, cast

from django.utils import timezone

from celery import shared_task

from queuetip.models import BulkImportJob, Contribution, Playlist
from src.queuetip.resolution.errors import (
    EditorialPlaylistError,
    PlaylistNotFoundError,
    ResolutionError,
    UnsupportedURLError,
)
from src.queuetip.resolution.ingest import ingest_track
from src.queuetip.resolution.playlists import resolve_playlist

logger = logging.getLogger(__name__)


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
            # get_or_create is race-safe on the (playlist, song) unique
            # constraint: a concurrent import of the same track is counted as a
            # skip rather than raising IntegrityError (which the bare except
            # above would have mis-counted as "unresolved").
            _, created = Contribution.objects.get_or_create(
                playlist=playlist,
                song=song,
                defaults={"contributed_by": job.requested_by},
            )
            if created:
                added += 1
            else:
                skipped += 1

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
