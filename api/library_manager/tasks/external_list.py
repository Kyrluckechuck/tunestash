"""Celery tasks for external music list syncing and track mapping."""

from datetime import timedelta
from typing import Any, Optional

from django.db import transaction
from django.utils import timezone

from celery_app import app as celery_app

from ..helpers import (
    enqueue_download_deezer_track,
    enqueue_download_track_by_spotify_gid,
    enqueue_map_external_list_tracks,
    generate_task_id,
    is_task_pending_or_running,
)
from ..models import (
    ExternalList,
    ExternalListStatus,
    ExternalListTrack,
    Song,
    TrackMappingCache,
    TrackMappingStatus,
)
from .core import (
    TaskPriority,
    complete_task,
    create_task_history,
    is_task_cancelled,
    logger,
    mark_task_running,
)

# Rows that failed for a temporary reason are retried on a later sync after
# this long, instead of waiting for the 90-day negative cache to expire.
TRANSIENT_RETRY_AFTER = timedelta(minutes=15)
TRANSIENT_METHOD = "error"


class _SyncCancelled(Exception):
    """Raised inside the reconcile transaction so a cancel rolls it back."""


def _refresh_list_counts(external_list: ExternalList) -> None:
    rows = ExternalListTrack.objects.filter(external_list=external_list)
    external_list.total_tracks = rows.count()
    external_list.mapped_tracks = rows.filter(
        mapping_status=TrackMappingStatus.MAPPED
    ).count()
    external_list.failed_tracks = rows.filter(
        mapping_status=TrackMappingStatus.FAILED
    ).count()


def _requeue_transient_failures(external_list: ExternalList) -> int:
    """Put rows that failed on a provider outage back to PENDING after a delay."""
    cutoff = timezone.now() - TRANSIENT_RETRY_AFTER
    return ExternalListTrack.objects.filter(
        external_list=external_list,
        mapping_status=TrackMappingStatus.FAILED,
        mapping_method=TRANSIENT_METHOD,
        mapped_at__lt=cutoff,
    ).update(
        mapping_status=TrackMappingStatus.PENDING,
        mapping_error=None,
        mapping_method=None,
    )


def _queue_pending_mapping(external_list: ExternalList) -> None:
    if ExternalListTrack.objects.filter(
        external_list=external_list,
        mapping_status=TrackMappingStatus.PENDING,
    ).exists():
        enqueue_map_external_list_tracks(
            external_list.id, priority=TaskPriority.PLAYLIST_DOWNLOAD
        )


def _reconcile_tracks(
    external_list: ExternalList,
    result: Any,
    task_id: str,
    allow_removals: bool,
) -> tuple[int, int, int]:
    """Make the list's rows match ``result`` in one transaction.

    Returns ``(created, updated, removed)``. Removal only drops the list's
    membership row: songs and files stay, and the song's other lists are
    untouched.
    """
    created_count = updated_count = 0
    keys: set[tuple[str, str]] = set()
    with transaction.atomic():
        for track in result.tracks:
            if is_task_cancelled(task_id):
                raise _SyncCancelled()
            key = (track.artist_name.lower().strip(), track.track_name.lower().strip())
            keys.add(key)
            _, created = ExternalListTrack.objects.update_or_create(
                external_list=external_list,
                artist_name=key[0],
                track_name=key[1],
                defaults={"musicbrainz_id": track.musicbrainz_id or None},
            )
            if created:
                created_count += 1
            else:
                updated_count += 1

        removed = 0
        if allow_removals:
            stale = [
                row.pk
                for row in ExternalListTrack.objects.filter(
                    external_list=external_list
                ).only("id", "artist_name", "track_name")
                if (row.artist_name, row.track_name) not in keys
            ]
            if stale:
                removed, _ = ExternalListTrack.objects.filter(pk__in=stale).delete()
        _refresh_list_counts(external_list)
    return created_count, updated_count, removed


def _sync_external_list_internal(
    external_list: ExternalList,
    force: bool = False,
    task_id: Optional[str] = None,
) -> None:
    """Fetch tracks from external source and reconcile ExternalListTrack rows."""
    from src.providers import get_provider

    task_history = create_task_history(
        task_id=task_id,
        task_type="SYNC",
        entity_id=str(external_list.pk),
        entity_type="PLAYLIST",
        task_name="sync_external_list",
    )
    mark_task_running(task_history)

    try:
        if is_task_cancelled(task_history.task_id):
            logger.info("[EXTERNAL_LIST] Sync cancelled for '%s'", external_list.name)
            return

        provider = get_provider(external_list.source)

        # Fetch all tracks
        result = provider.fetch_all_tracks(
            username=external_list.username,
            list_type=external_list.list_type,
            period=external_list.period,
            list_identifier=external_list.list_identifier,
        )

        _requeue_transient_failures(external_list)

        # Check content hash — skip if unchanged (unless force)
        if (
            not force
            and external_list.content_hash
            and external_list.content_hash == result.content_hash
        ):
            logger.info(
                "[EXTERNAL_LIST] No changes for '%s' (hash unchanged)",
                external_list.name,
            )
            external_list.last_synced_at = timezone.now()
            _refresh_list_counts(external_list)
            external_list.save(
                update_fields=[
                    "last_synced_at",
                    "total_tracks",
                    "mapped_tracks",
                    "failed_tracks",
                ]
            )
            _queue_pending_mapping(external_list)
            complete_task(task_history, success=True)
            return

        # An empty answer for a list that has tracks is far more likely a failed
        # or truncated fetch than the user emptying it; never wipe on that.
        had_rows = ExternalListTrack.objects.filter(
            external_list=external_list
        ).exists()
        if not result.tracks and had_rows:
            message = "Upstream returned no tracks; kept the existing list"
            logger.warning("[EXTERNAL_LIST] %s for '%s'", message, external_list.name)
            external_list.status_message = message
            external_list.save(update_fields=["status_message"])
            complete_task(task_history, success=False, error_message=message)
            return

        # Removals need the provider's positive proof of a complete fetch.
        complete_fetch = result.complete is True
        if not complete_fetch:
            logger.warning(
                "[EXTERNAL_LIST] Partial fetch for '%s'; adding tracks but "
                "not removing any",
                external_list.name,
            )

        try:
            created_count, updated_count, removed_count = _reconcile_tracks(
                external_list,
                result,
                task_history.task_id,
                allow_removals=complete_fetch,
            )
        except _SyncCancelled:
            logger.info("[EXTERNAL_LIST] Sync cancelled for '%s'", external_list.name)
            return

        # Update list metadata. A partial fetch keeps no hash so the next sync
        # re-reconciles instead of treating the prefix as the whole list.
        external_list.content_hash = result.content_hash if complete_fetch else None
        external_list.last_synced_at = timezone.now()
        external_list.status = ExternalListStatus.ACTIVE
        external_list.status_message = None
        external_list.save()

        logger.info(
            "[EXTERNAL_LIST] Synced '%s': %d new, %d updated, %d removed, %d total",
            external_list.name,
            created_count,
            updated_count,
            removed_count,
            external_list.total_tracks,
        )

        _queue_pending_mapping(external_list)

        complete_task(task_history, success=True)

    except Exception as e:
        logger.error("[EXTERNAL_LIST] Sync error for '%s': %s", external_list.name, e)
        external_list.status_message = str(e)[:255]

        error_str = str(e).lower()
        if "not found" in error_str:
            external_list.status = ExternalListStatus.NOT_FOUND
        elif "auth" in error_str or "token" in error_str:
            external_list.status = ExternalListStatus.AUTH_ERROR
        else:
            external_list.status = ExternalListStatus.SYNC_ERROR
        external_list.save()

        complete_task(task_history, success=False, error_message=str(e))


@celery_app.task(bind=True, name="library_manager.tasks.sync_external_list")
def sync_external_list(
    self: Any, list_id: int, force: bool = False, task_id: Optional[str] = None
) -> None:
    """Celery task: sync an external list."""
    if task_id is None:
        task_id = self.request.id

    try:
        external_list = ExternalList.objects.get(id=list_id)
    except ExternalList.DoesNotExist:
        logger.warning("[EXTERNAL_LIST] List ID %d not found, skipping", list_id)
        return

    _sync_external_list_internal(external_list, force=force, task_id=task_id)


def _song_for_deezer_track(deezer_id: int) -> tuple[Optional[Song], Optional[str]]:
    """Create the local Song for a Deezer track that exists only upstream.

    Returns ``(song, error)``; ``error`` set with no song means a temporary
    failure worth retrying.
    """
    from src.providers.deezer import DeezerMetadataProvider

    from ..artist_credits import create_song_with_credits

    existing = Song.objects.filter(deezer_id=deezer_id).first()
    if existing:
        return existing, None
    provider = DeezerMetadataProvider()
    track = provider.get_track(deezer_id)
    if track is None:
        return None, f"Deezer track {deezer_id} unavailable"
    song = create_song_with_credits(track, provider=provider)
    if song is None:
        return None, f"Deezer track {deezer_id}: artist identity unresolved"
    return song, None


def _apply_mapping(track_obj: ExternalListTrack, mapping: Any) -> bool:
    """Record one mapping outcome; True when the row ended up MAPPED."""
    from src.services.track_mapping import PROVIDER_DEEZER, PROVIDER_SPOTIFY

    now = timezone.now()
    track_obj.mapped_at = now
    track_obj.mapping_method = mapping.method

    if not mapping.mapped:
        track_obj.mapping_status = TrackMappingStatus.FAILED
        track_obj.mapping_error = (mapping.error or "Unknown error")[:255]
        track_obj.save()
        return False

    song = Song.objects.filter(pk=mapping.song_id).first() if mapping.song_id else None
    error: Optional[str] = None
    if song is None and mapping.provider == PROVIDER_DEEZER:
        try:
            song, error = _song_for_deezer_track(int(mapping.provider_id))
        except Exception as e:  # provider outage: retry later
            logger.warning("[TRACK_MAPPING] Deezer track create failed: %s", e)
            song, error = None, f"Temporary error, will retry: {e}"
        if song is None:
            track_obj.mapping_status = TrackMappingStatus.FAILED
            track_obj.mapping_error = (error or "Unknown error")[:255]
            track_obj.mapping_method = TRANSIENT_METHOD
            track_obj.save()
            return False
        enqueue_download_deezer_track(song.pk, priority=TaskPriority.TRACK_DOWNLOAD)

    track_obj.mapping_status = TrackMappingStatus.MAPPED
    track_obj.mapping_confidence = mapping.confidence
    track_obj.mapping_error = None
    # Only a Spotify id belongs in this column; Deezer ids are kept on the Song.
    track_obj.spotify_track_id = (
        mapping.provider_id if mapping.provider == PROVIDER_SPOTIFY else None
    )
    if song is not None:
        track_obj.song = song
    elif mapping.provider == PROVIDER_SPOTIFY and mapping.provider_id:
        enqueue_download_track_by_spotify_gid(
            mapping.provider_id, priority=TaskPriority.TRACK_DOWNLOAD
        )
    track_obj.save()
    return True


def _map_external_list_tracks_internal(
    external_list: ExternalList,
    batch_size: int = 50,
    task_id: Optional[str] = None,
) -> None:
    """Map PENDING tracks using the mapping pipeline.

    Owns the task's TaskHistory claim: it is adopted and marked RUNNING here,
    left RUNNING for the next batch when the chain continues, and completed or
    failed when the chain ends.
    """
    task_history = create_task_history(
        task_id=task_id
        or generate_task_id(
            "library_manager.tasks.map_external_list_tracks", external_list.id
        ),
        task_type="SYNC",
        entity_id=str(external_list.id),
        entity_type="PLAYLIST",
        task_name="map_external_list_tracks",
    )
    mark_task_running(task_history)
    claim_id = task_history.task_id

    try:
        if _map_batch(external_list, batch_size, claim_id):
            complete_task(task_history, success=True)
    except Exception as e:
        complete_task(task_history, success=False, error_message=str(e))
        raise


def _map_batch(external_list: ExternalList, batch_size: int, claim_id: str) -> bool:
    """Map one batch. Returns True when the chain is finished (and not cancelled)."""
    from src.services.track_mapping import TrackMappingService

    mapping_service = TrackMappingService()

    pending_tracks = list(
        ExternalListTrack.objects.filter(
            external_list=external_list,
            mapping_status=TrackMappingStatus.PENDING,
        )[:batch_size]
    )

    if not pending_tracks:
        return True

    logger.info(
        "[TRACK_MAPPING] Mapping %d tracks for '%s'",
        len(pending_tracks),
        external_list.name,
    )

    # Build batch input
    batch_input = [
        (t.artist_name, t.track_name, t.musicbrainz_id) for t in pending_tracks
    ]

    if is_task_cancelled(claim_id):
        logger.info("[TRACK_MAPPING] Mapping cancelled for '%s'", external_list.name)
        return False

    results = mapping_service.map_tracks_batch(batch_input)

    mapped_count = 0
    failed_count = 0

    for track_obj, mapping in zip(pending_tracks, results):
        if is_task_cancelled(claim_id):
            logger.info(
                "[TRACK_MAPPING] Mapping cancelled for '%s'", external_list.name
            )
            return False
        if _apply_mapping(track_obj, mapping):
            mapped_count += 1
        else:
            failed_count += 1

    # Update list stats
    _refresh_list_counts(external_list)
    external_list.save(update_fields=["total_tracks", "mapped_tracks", "failed_tracks"])

    logger.info(
        "[TRACK_MAPPING] Batch complete for '%s': %d mapped, %d failed",
        external_list.name,
        mapped_count,
        failed_count,
    )

    # Chain to self if more PENDING tracks remain
    remaining = ExternalListTrack.objects.filter(
        external_list=external_list,
        mapping_status=TrackMappingStatus.PENDING,
    ).count()

    if remaining > 0:
        logger.info(
            "[TRACK_MAPPING] %d tracks remaining for '%s', chaining next batch",
            remaining,
            external_list.name,
        )
        # Reuse the deterministic id so external triggers dedupe against this
        # chain. A plain apply_async bypasses the claim check: the current batch
        # still holds the claim, and the next batch adopts it when it starts.
        map_external_list_tracks.apply_async(
            args=[external_list.id],
            task_id=claim_id,
        )
        return False
    return True


@celery_app.task(bind=True, name="library_manager.tasks.map_external_list_tracks")
def map_external_list_tracks(
    self: Any, list_id: int, task_id: Optional[str] = None
) -> None:
    """Celery task: map pending tracks for an external list to Spotify IDs."""
    if task_id is None:
        task_id = self.request.id

    try:
        external_list = ExternalList.objects.get(id=list_id)
    except ExternalList.DoesNotExist:
        logger.warning("[TRACK_MAPPING] List ID %d not found, skipping", list_id)
        return

    _map_external_list_tracks_internal(external_list, task_id=task_id)


@celery_app.task(bind=True, name="library_manager.tasks.sync_all_external_lists")
def sync_all_external_lists(self: Any) -> None:
    """Periodic task: sync all active external lists."""
    active_lists = ExternalList.objects.filter(status=ExternalListStatus.ACTIVE)

    queued = 0
    for ext_list in active_lists:
        task_id_str = generate_task_id(
            "library_manager.tasks.sync_external_list", ext_list.id
        )
        is_pending, reason = is_task_pending_or_running(task_id_str)
        if is_pending:
            logger.info(
                "[EXTERNAL_LIST] Skipping sync for '%s': %s", ext_list.name, reason
            )
            continue

        sync_external_list.apply_async(
            args=[ext_list.id],
            task_id=task_id_str,
            priority=TaskPriority.PLAYLIST_DOWNLOAD,
        )
        queued += 1

    logger.info("[EXTERNAL_LIST] Queued sync for %d active external lists", queued)


@celery_app.task(bind=True, name="library_manager.tasks.cleanup_mapping_cache")
def cleanup_mapping_cache(self: Any) -> None:
    """Periodic task: remove expired negative cache entries (>90 days old)."""
    cutoff = timezone.now() - timedelta(days=90)
    deleted_count, _ = TrackMappingCache.objects.filter(
        no_match=True,
        created_at__lt=cutoff,
    ).delete()

    if deleted_count > 0:
        logger.info(
            "[TRACK_MAPPING] Cleaned up %d expired negative cache entries",
            deleted_count,
        )


@celery_app.task(bind=True, name="library_manager.tasks.retry_failed_external_mappings")
def retry_failed_external_mappings(self: Any) -> None:
    """One-off task: reset failed mappings to PENDING and clear negative cache."""
    # Clear negative cache entries so they'll be re-tried
    neg_deleted, _ = TrackMappingCache.objects.filter(no_match=True).delete()

    # Reset failed tracks to pending
    updated = ExternalListTrack.objects.filter(
        mapping_status=TrackMappingStatus.FAILED,
    ).update(
        mapping_status=TrackMappingStatus.PENDING,
        mapping_error=None,
        mapping_method=None,
    )

    logger.info(
        "[TRACK_MAPPING] Retry failed mappings: %d tracks reset, %d cache entries cleared",
        updated,
        neg_deleted,
    )

    # Queue mapping for lists with pending tracks
    list_ids = (
        ExternalListTrack.objects.filter(
            mapping_status=TrackMappingStatus.PENDING,
        )
        .values_list("external_list_id", flat=True)
        .distinct()
    )
    for list_id in list_ids:
        enqueue_map_external_list_tracks(
            list_id, priority=TaskPriority.PLAYLIST_DOWNLOAD
        )
