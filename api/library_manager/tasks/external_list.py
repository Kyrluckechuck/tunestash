"""Celery tasks for external music list syncing and track mapping."""

from datetime import timedelta
from typing import Any, Optional

from django.utils import timezone

from celery_app import app as celery_app

from ..helpers import generate_task_id, is_task_pending_or_running
from ..models import (
    ExternalList,
    ExternalListStatus,
    ExternalListTrack,
    Song,
    TrackMappingCache,
    TrackMappingStatus,
)
from .core import TaskPriority, complete_task, create_task_history, logger


def _sync_external_list_internal(
    external_list: ExternalList,
    force: bool = False,
    task_id: Optional[str] = None,
) -> None:
    """Fetch tracks from external source and upsert ExternalListTrack rows."""
    from src.providers import get_provider

    task_history = create_task_history(
        task_id=task_id,
        task_type="SYNC",
        entity_id=str(external_list.pk),
        entity_type="PLAYLIST",
        task_name="sync_external_list",
    )
    task_history.status = "RUNNING"
    task_history.save()

    try:
        provider = get_provider(external_list.source)

        # Fetch all tracks
        result = provider.fetch_all_tracks(
            username=external_list.username,
            list_type=external_list.list_type,
            period=external_list.period,
            list_identifier=external_list.list_identifier,
        )

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
            external_list.save(update_fields=["last_synced_at"])
            complete_task(task_history, success=True)
            return

        # Upsert tracks
        created_count = 0
        updated_count = 0
        for track in result.tracks:
            normalized_artist = track.artist_name.lower().strip()
            normalized_track = track.track_name.lower().strip()

            obj, created = ExternalListTrack.objects.update_or_create(
                external_list=external_list,
                artist_name=normalized_artist,
                track_name=normalized_track,
                defaults={
                    "musicbrainz_id": track.musicbrainz_id or None,
                },
            )
            if created:
                created_count += 1
            else:
                updated_count += 1

        # Update list metadata
        external_list.content_hash = result.content_hash
        external_list.last_synced_at = timezone.now()
        external_list.total_tracks = ExternalListTrack.objects.filter(
            external_list=external_list
        ).count()
        external_list.status = ExternalListStatus.ACTIVE
        external_list.status_message = None
        external_list.save()

        logger.info(
            "[EXTERNAL_LIST] Synced '%s': %d new, %d updated, %d total",
            external_list.name,
            created_count,
            updated_count,
            external_list.total_tracks,
        )

        # Queue track mapping for PENDING tracks
        pending_count = ExternalListTrack.objects.filter(
            external_list=external_list,
            mapping_status=TrackMappingStatus.PENDING,
        ).count()

        if pending_count > 0:
            map_external_list_tracks.delay(external_list.id)

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


def _map_external_list_tracks_internal(
    external_list: ExternalList,
    batch_size: int = 50,
    task_id: Optional[str] = None,
) -> None:
    """Map PENDING tracks to Spotify IDs using the mapping pipeline."""
    from src.services.track_mapping import TrackMappingService

    mapping_service = TrackMappingService()

    pending_tracks = list(
        ExternalListTrack.objects.filter(
            external_list=external_list,
            mapping_status=TrackMappingStatus.PENDING,
        )[:batch_size]
    )

    if not pending_tracks:
        return

    logger.info(
        "[TRACK_MAPPING] Mapping %d tracks for '%s'",
        len(pending_tracks),
        external_list.name,
    )

    # Build batch input
    batch_input = [
        (t.artist_name, t.track_name, t.musicbrainz_id) for t in pending_tracks
    ]

    results = mapping_service.map_tracks_batch(batch_input)

    mapped_count = 0
    failed_count = 0

    for track_obj, (result_id, method, confidence, error) in zip(
        pending_tracks, results
    ):
        if result_id:
            track_obj.mapping_status = TrackMappingStatus.MAPPED
            track_obj.spotify_track_id = result_id
            track_obj.mapping_confidence = confidence
            track_obj.mapping_method = method
            track_obj.mapped_at = timezone.now()
            track_obj.mapping_error = None

            # Try to find Song — prefer deezer_id for Deezer-resolved tracks
            song = None
            if method == "deezer_search":
                try:
                    deezer_id = int(result_id)
                    song = Song.objects.filter(deezer_id=deezer_id).first()
                except (ValueError, TypeError):
                    pass

            if not song:
                song = Song.objects.filter(gid=result_id).first()

            if song:
                track_obj.song = song
            else:
                # Queue download via appropriate path
                if method == "deezer_search":
                    try:
                        deezer_id = int(result_id)
                        from library_manager.tasks import download_deezer_track

                        download_deezer_track.delay(deezer_id)
                    except (ValueError, TypeError):
                        pass
                else:
                    from library_manager.tasks import download_track_by_spotify_gid

                    download_track_by_spotify_gid.delay(result_id)

            track_obj.save()
            mapped_count += 1
        else:
            track_obj.mapping_status = TrackMappingStatus.FAILED
            track_obj.mapping_error = (error or "Unknown error")[:255]
            track_obj.mapping_method = method
            track_obj.mapped_at = timezone.now()
            track_obj.save()
            failed_count += 1

    # Update list stats
    external_list.mapped_tracks = ExternalListTrack.objects.filter(
        external_list=external_list,
        mapping_status=TrackMappingStatus.MAPPED,
    ).count()
    external_list.failed_tracks = ExternalListTrack.objects.filter(
        external_list=external_list,
        mapping_status=TrackMappingStatus.FAILED,
    ).count()
    external_list.save(update_fields=["mapped_tracks", "failed_tracks"])

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
        map_external_list_tracks.delay(external_list.id)


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
        map_external_list_tracks.delay(list_id)
