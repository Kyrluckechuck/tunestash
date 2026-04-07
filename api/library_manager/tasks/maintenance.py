"""Maintenance tasks for the Tunestash."""

import asyncio
from typing import Any, Optional

from celery_app import app as celery_app

from ..models import Album, Artist
from ..models import DownloadProvider as DownloadProviderEnum
from ..models import Song
from .core import (
    complete_task,
    create_task_history,
    logger,
    normalize_name,
    require_download_capability,
    update_task_progress,
)
from .download import DEFAULT_FALLBACK_ORDER, FALLBACK_PROVIDER_MAP


def _try_resolve_to_deezer(song: Song) -> None:
    """Attempt to link a song to Deezer before downloading, for richer metadata."""
    if song.deezer_id:
        return

    from src.providers.deezer import DeezerMetadataProvider

    provider = DeezerMetadataProvider()

    # Try ISRC first (most reliable)
    if song.isrc:
        try:
            result = provider.get_track_by_isrc(song.isrc)
            if result and result.deezer_id:
                if Song.objects.filter(deezer_id=result.deezer_id).exists():
                    logger.info(
                        "Song %d: deezer_id=%d (via ISRC) already claimed, skipping",
                        song.id,
                        result.deezer_id,
                    )
                    return
                song.deezer_id = result.deezer_id
                song.save(update_fields=["deezer_id"])
                logger.debug(
                    "Linked song %s to Deezer %d via ISRC", song.id, result.deezer_id
                )
                return
        except Exception as e:
            logger.debug("ISRC lookup failed for song %s: %s", song.id, e)

    # Fall back to name search
    artist_name = (
        song.primary_artist.name  # type: ignore[attr-defined]
        if song.primary_artist
        else ""
    )
    if artist_name and song.name:
        try:
            results = provider.search_tracks(f"{artist_name} {song.name}", limit=5)
            norm_song = normalize_name(song.name)
            norm_artist = normalize_name(artist_name)
            for track in results:
                if (
                    normalize_name(track.name) == norm_song
                    and normalize_name(track.artist_name or "") == norm_artist
                    and track.deezer_id
                ):
                    if Song.objects.filter(deezer_id=track.deezer_id).exists():
                        logger.info(
                            "Song %d: deezer_id=%d (via search) already claimed, "
                            "skipping",
                            song.id,
                            track.deezer_id,
                        )
                        return
                    song.deezer_id = track.deezer_id
                    song.save(update_fields=["deezer_id"])
                    logger.debug(
                        "Linked song %s to Deezer %d via name search",
                        song.id,
                        track.deezer_id,
                    )
                    return
        except Exception as e:
            logger.debug("Name search failed for song %s: %s", song.id, e)


def _build_track_metadata(song: Song) -> Any:
    """Build TrackMetadata for a song, enriching from Deezer when available."""
    from downloader.providers.base import TrackMetadata

    artist_name = song.primary_artist.name  # type: ignore[attr-defined]
    album_name = song.album.name if song.album else ""  # type: ignore[attr-defined]
    duration_ms = 0
    isrc = song.isrc

    # Enrich from Deezer API for missing fields
    if song.deezer_id:
        try:
            from src.providers.deezer import DeezerMetadataProvider

            dz_track = DeezerMetadataProvider().get_track(song.deezer_id)
            if dz_track:
                if not album_name and dz_track.album_name:
                    album_name = dz_track.album_name
                if dz_track.duration_ms:
                    duration_ms = dz_track.duration_ms
                if not isrc and dz_track.isrc:
                    isrc = dz_track.isrc
                if dz_track.artist_name:
                    artist_name = dz_track.artist_name
        except Exception:
            pass

    return TrackMetadata(
        spotify_id="",
        title=song.name,
        artist=artist_name,
        album=album_name,
        album_artist=artist_name,
        duration_ms=duration_ms,
        isrc=isrc,
    )


def _download_deezer_songs_via_fallback(songs: list[Song]) -> tuple[int, int]:
    """Download songs via YouTube/Tidal/Qobuz fallback providers.

    For each song, attempts to resolve to Deezer first for richer metadata,
    then downloads via FallbackDownloader.

    Returns (downloaded_count, failed_count).
    """
    from downloader.providers.fallback import FallbackDownloader

    downloader = FallbackDownloader(
        provider_order=DEFAULT_FALLBACK_ORDER,
    )

    downloaded = 0
    failed = 0

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        for song in songs:
            _try_resolve_to_deezer(song)
            metadata = _build_track_metadata(song)

            result = loop.run_until_complete(downloader.download_track(metadata))

            if result.success and result.file_path:
                dl_provider = FALLBACK_PROVIDER_MAP.get(
                    result.provider_used or "", DownloadProviderEnum.UNKNOWN
                )
                song.mark_downloaded(
                    bitrate=256,
                    file_path=str(result.file_path),
                    provider=dl_provider,
                )
                downloaded += 1
            else:
                failed += 1
                song.increment_failed_count()
                song.save()

    finally:
        try:
            loop.run_until_complete(downloader.close())
        finally:
            loop.close()

    return downloaded, failed


@celery_app.task(
    bind=True,
    autoretry_for=(Exception,),
    retry_kwargs={"max_retries": 2, "countdown": 30},
    name="library_manager.tasks.retry_all_missing_known_songs",
)
def retry_all_missing_known_songs(self: Any, task_id: Optional[str] = None) -> None:
    # Check authentication before proceeding with any DB queries
    require_download_capability()

    missing_known_songs_list = (
        Song.objects.filter(bitrate=0, unavailable=False)
        .order_by("created_at")
        .select_related("primary_artist")
        .filter(primary_artist__tracking_tier__gte=1)[:100]
    )
    failed_known_songs_list = Song.objects.filter(
        failed_count__gt=0, bitrate=0, unavailable=False
    ).order_by("created_at")[:100]
    # Combine results for iterating
    missing_known_songs_list = missing_known_songs_list | failed_known_songs_list

    if missing_known_songs_list.count() == 0:
        logger.info("All songs downloaded, exiting missing known song loop!")
        return

    songs_to_download = []
    for song in missing_known_songs_list.iterator():
        if song.gid or song.deezer_id:
            songs_to_download.append(song)
        else:
            logger.warning(f"Song {song.id} has no provider ID, skipping")

    if songs_to_download:
        logger.info(
            f"Downloading {len(songs_to_download)} missing songs via fallback providers"
        )
        downloaded, failed = _download_deezer_songs_via_fallback(songs_to_download)
        logger.info(f"Missing songs: {downloaded} downloaded, {failed} failed")


@celery_app.task(
    bind=True, name="library_manager.tasks.cleanup_stuck_tasks_periodic"
)  # Scheduled via Celery Beat - Every 5 minutes
def cleanup_stuck_tasks_periodic(self: Any) -> None:
    """Periodically clean up stuck tasks and stale TaskResult records."""
    from datetime import timedelta

    from django.utils import timezone

    from django_celery_results.models import TaskResult

    from library_manager.models import TaskHistory

    # Clean up stuck TaskHistory records
    stuck_count = TaskHistory.cleanup_stuck_tasks()
    if stuck_count > 0:
        logger.info(f"Cleaned up {stuck_count} stuck TaskHistory record(s)")

    # Clean up stale TaskResult records stuck in STARTED status
    # These can accumulate when tasks crash without proper cleanup
    stale_threshold = timezone.now() - timedelta(minutes=30)
    stale_results = TaskResult.objects.filter(
        status="STARTED",
        date_created__lt=stale_threshold,
    ).update(status="FAILURE")

    if stale_results > 0:
        logger.info(f"Cleaned up {stale_results} stale TaskResult record(s)")


@celery_app.task(
    bind=True, name="library_manager.tasks.cleanup_celery_history"
)  # Scheduled via Celery Beat - Daily at 6 AM
def cleanup_celery_history(self: Any, days_to_keep: int = 30) -> None:
    """Periodically clean up old completed/failed task history to prevent database bloat"""
    from library_manager.models import TaskHistory

    deleted_count = TaskHistory.cleanup_old_tasks(days_to_keep=days_to_keep)
    if deleted_count > 0:
        logger.info(f"Cleaned up {deleted_count} old task history record(s)")
    else:
        logger.info("No old task history records to clean up")


@celery_app.task(
    bind=True, name="library_manager.tasks.cleanup_app_metrics"
)  # Scheduled via Celery Beat - Daily at 6 AM
def cleanup_app_metrics(self: Any, days_to_keep: int = 30) -> None:
    """Periodically clean up old app metrics to prevent database bloat."""
    from src.services.metrics import MetricsService

    deleted_count = MetricsService.cleanup_old_metrics(days=days_to_keep)
    if deleted_count > 0:
        logger.info(f"Cleaned up {deleted_count} old app metric record(s)")
    else:
        logger.info("No old app metrics to clean up")


@celery_app.task(
    bind=True,
    autoretry_for=(Exception,),
    retry_kwargs={"max_retries": 2, "countdown": 30},
    name="library_manager.tasks.validate_undownloaded_songs",
)  # Scheduled via Celery Beat - Every 12 hours
def validate_undownloaded_songs(
    self: Any,
    task_id: Optional[str] = None,
) -> None:
    """
    Validate and re-download songs that should exist but aren't downloaded.

    Processes up to 100 songs per run. Each song can only be attempted once per week
    (tracked via last_download_attempt field). Runs every 12 hours but respects
    the weekly per-song limit.
    """
    from datetime import timedelta

    from django.db.models import Q
    from django.utils import timezone

    # Check authentication before proceeding with any DB queries
    require_download_capability()

    # Only attempt songs that haven't been tried in the last 7 days
    one_week_ago = timezone.now() - timedelta(days=7)
    not_recently_attempted = Q(last_download_attempt__isnull=True) | Q(
        last_download_attempt__lt=one_week_ago
    )

    non_downloaded_songs_that_should_exist = (
        Song.objects.filter(bitrate__gt=0, unavailable=False, downloaded=False)
        .filter(not_recently_attempted)
        .order_by("created_at")[:100]
    )
    non_downloaded_songs_that_maybe_should_exist = (
        Song.objects.filter(bitrate__gt=0, unavailable=True, downloaded=False)
        .filter(not_recently_attempted)
        .order_by("created_at")[:100]
    )

    non_downloaded_songs = (
        non_downloaded_songs_that_should_exist
        | non_downloaded_songs_that_maybe_should_exist
    )

    non_downloaded_songs_count = non_downloaded_songs.count()

    # No songs to attempt
    if non_downloaded_songs_count == 0:
        logger.info(
            "No songs to validate (all downloaded or attempted within last week)"
        )
        return

    song_ids = []
    songs_to_download = []
    for song in non_downloaded_songs.iterator():
        if song.gid or song.deezer_id:
            songs_to_download.append(song)
            song_ids.append(song.id)
        else:
            logger.warning(f"Song {song.id} has no provider ID, skipping")

    Song.objects.filter(id__in=song_ids).update(last_download_attempt=timezone.now())

    if songs_to_download:
        logger.info(
            f"Downloading {len(songs_to_download)} missing songs via fallback providers"
        )
        downloaded, failed = _download_deezer_songs_via_fallback(songs_to_download)
        logger.info(f"Validation: {downloaded} downloaded, {failed} failed")

    logger.info(f"Completed validation attempt for {non_downloaded_songs_count} songs")


@celery_app.task(
    bind=True, name="library_manager.tasks.retry_failed_songs"
)  # Scheduled via Celery Beat - 3 times per week
def retry_failed_songs(self: Any) -> None:
    """
    Periodically retry downloading songs that have previously failed.

    Uses smart exponential backoff based on failure reason:
    - TEMPORARY_ERROR: 1, 2, 4, 7 days (capped)
    - SPOTIFY_NOT_FOUND/YTM_NO_MATCH: 2, 4, 8, 16, 30 days (capped)
    - BOTH_UNAVAILABLE: 30 days flat

    Processes up to 100 songs per run, ordered by:
    1. failed_count ASC (fewer failures = higher priority)
    2. created_at ASC (older songs = higher priority within same failure count)

    Songs with >10 failures are skipped (likely permanently unavailable).
    Runs 3 times per week (Mon/Wed/Fri).
    """
    from ..models import FailureReason

    try:
        logger.info("Starting periodic retry of failed songs")

        # Check authentication before proceeding
        require_download_capability()

        # Find songs that have failed but might succeed on retry
        # Priority: songs with fewer failures first
        candidate_songs = Song.objects.filter(
            downloaded=False,
            failed_count__gt=0,
            failed_count__lte=10,  # Skip songs that have failed too many times
        ).order_by("failed_count", "created_at")[
            :200
        ]  # Fetch extra to filter

        if not candidate_songs.exists():
            logger.info("No failed songs to retry")
            return

        # Filter to only songs that are ready for retry (past their backoff period)
        songs_to_retry = []
        skipped_count = 0
        for song in candidate_songs.iterator():
            if song.is_ready_for_retry():
                songs_to_retry.append(song)
                if len(songs_to_retry) >= 100:
                    break
            else:
                skipped_count += 1

        if not songs_to_retry:
            logger.info("No failed songs ready for retry (all in backoff period)")
            return

        # Log stats about what we're skipping vs retrying
        if skipped_count > 0:
            logger.info(f"Skipped {skipped_count} songs still in backoff period")

        song_count = len(songs_to_retry)
        logger.info(f"Found {song_count} failed songs ready for retry")

        # Log some stats about what we're retrying
        failure_counts: dict[int, int] = {}
        failure_reasons: dict[str, int] = {}
        for song in songs_to_retry:
            failure_counts[song.failed_count] = (
                failure_counts.get(song.failed_count, 0) + 1
            )
            if song.failure_reason:
                reason_label = str(FailureReason(song.failure_reason).label)
            else:
                reason_label = "Unknown"
            failure_reasons[reason_label] = failure_reasons.get(reason_label, 0) + 1

        logger.info(f"Retry batch failure count distribution: {failure_counts}")
        logger.info(f"Retry batch failure reason distribution: {failure_reasons}")

        songs_to_download = []
        for s in songs_to_retry:
            if s.gid or s.deezer_id:
                songs_to_download.append(s)
            else:
                logger.warning(f"Song {s.id} has no provider ID, skipping")

        if songs_to_download:
            logger.info(
                f"Starting download retry for {len(songs_to_download)} songs "
                f"via fallback providers"
            )
            downloaded, failed = _download_deezer_songs_via_fallback(songs_to_download)
            logger.info(f"Retry: {downloaded} downloaded, {failed} failed")

        logger.info(f"Completed retry attempt for {song_count} songs")

    except Exception as e:
        logger.error(f"Error in retry_failed_songs: {e}", exc_info=True)


@celery_app.task(bind=True, name="library_manager.tasks.retry_failed_songs_for_artist")
def retry_failed_songs_for_artist(self: Any, artist_id: int) -> None:
    """
    Retry downloading failed songs for a specific artist.

    Unlike the global retry_failed_songs task, this:
    - Ignores backoff periods (forces immediate retry)
    - Only processes songs for the specified artist
    - Still respects the max 10 failure limit
    """
    task_history = None
    try:
        artist = Artist.objects.get(id=artist_id)

        task_history = create_task_history(
            task_id=self.request.id,
            task_type="DOWNLOAD",
            entity_id=str(artist.id),
            entity_type="ARTIST",
        )
        update_task_progress(
            task_history, 0.0, f"Retrying failed songs for {artist.name}"
        )

        require_download_capability(task_history)

        # Find failed songs for this artist (ignoring backoff)
        failed_songs = Song.objects.filter(
            primary_artist=artist,
            downloaded=False,
            failed_count__gt=0,
            failed_count__lte=10,
            unavailable=False,
        ).order_by("failed_count", "created_at")[:100]

        if not failed_songs.exists():
            task_history.add_log_message("No failed songs to retry")
            complete_task(task_history, success=True)
            return

        song_count = failed_songs.count()
        update_task_progress(
            task_history, 25.0, f"Found {song_count} failed songs to retry"
        )

        songs_to_download = []
        for s in failed_songs:
            if s.gid or s.deezer_id:
                songs_to_download.append(s)
            else:
                logger.warning(f"Song {s.id} has no provider ID, skipping")

        if songs_to_download:
            logger.info(
                f"Retrying {len(songs_to_download)} songs "
                f"for artist {artist.name} via fallback providers"
            )
            downloaded, failed = _download_deezer_songs_via_fallback(songs_to_download)
            logger.info(
                f"Retry for {artist.name}: " f"{downloaded} downloaded, {failed} failed"
            )

        task_history.add_log_message(f"Retried {song_count} failed songs")
        complete_task(task_history, success=True)

    except Exception as e:
        logger.error(f"Error retrying failed songs for artist {artist_id}: {e}")
        if task_history:
            complete_task(task_history, success=False, error_message=str(e))
        raise


@celery_app.task(bind=True, name="library_manager.tasks.backfill_song_isrc")
def backfill_song_isrc(
    self: Any, songs_per_task: int = 250, last_song_id: int = 0
) -> None:
    """Backfill ISRC codes for songs using Deezer track metadata.

    Processes songs that have a deezer_id but no ISRC. Fetches each track
    individually from Deezer API, then bulk-updates the database.
    Self-chains until all songs are processed.

    Args:
        songs_per_task: Number of songs to process per task invocation.
        last_song_id: ID of the last song processed in the previous task.
    """
    import time

    from src.providers.deezer import DeezerMetadataProvider

    songs_without_isrc = list(
        Song.objects.filter(
            isrc__isnull=True,
            deezer_id__isnull=False,
            id__gt=last_song_id,
        )
        .order_by("id")
        .values_list("id", "deezer_id")[:songs_per_task]
    )

    if not songs_without_isrc:
        total_no_deezer = Song.objects.filter(
            isrc__isnull=True, deezer_id__isnull=True
        ).count()
        if total_no_deezer > 0:
            logger.info(
                f"ISRC backfill complete - {total_no_deezer} songs remain "
                f"without ISRC (no deezer_id)"
            )
        else:
            logger.info("ISRC backfill complete - no more songs without ISRC")
        return

    max_song_id = songs_without_isrc[-1][0]

    logger.info(f"Backfilling ISRC for {len(songs_without_isrc)} songs via Deezer")

    try:
        provider = DeezerMetadataProvider()
        total_updated = 0
        total_no_isrc = 0
        songs_to_update = []

        for song_id, deezer_id in songs_without_isrc:
            track = provider.get_track(deezer_id)
            if track and track.isrc:
                songs_to_update.append((song_id, track.isrc))
            else:
                total_no_isrc += 1

            time.sleep(0.1)

        if songs_to_update:
            song_objs = list(
                Song.objects.filter(id__in=[s[0] for s in songs_to_update])
            )
            isrc_map = dict(songs_to_update)
            for song in song_objs:
                song.isrc = isrc_map[song.id]
            Song.objects.bulk_update(song_objs, ["isrc"])
            total_updated = len(song_objs)

        logger.info(
            f"Updated {total_updated}/{len(songs_without_isrc)} songs with ISRC "
            f"({total_no_isrc} tracks had no ISRC on Deezer)"
        )

        remaining_after = Song.objects.filter(
            isrc__isnull=True, deezer_id__isnull=False, id__gt=max_song_id
        ).count()

        if remaining_after > 0:
            logger.info(
                f"{remaining_after} songs still need ISRC, scheduling next batch"
            )
            backfill_song_isrc.apply_async(
                kwargs={
                    "songs_per_task": songs_per_task,
                    "last_song_id": max_song_id,
                },
                countdown=30,
            )
        else:
            total_without_isrc = Song.objects.filter(isrc__isnull=True).count()
            if total_without_isrc > 0:
                logger.info(
                    f"ISRC backfill complete - {total_without_isrc} songs remain "
                    f"without ISRC (no deezer_id or not available on Deezer)"
                )
            else:
                logger.info("ISRC backfill complete - all songs have ISRC")

    except Exception as e:
        logger.error(f"Error during ISRC backfill: {e}", exc_info=True)
        raise


@celery_app.task(bind=True, name="library_manager.tasks.backfill_song_album")
def backfill_song_album(
    self: Any, songs_per_task: int = 250, last_song_id: int = 0
) -> None:
    """Backfill album associations for songs using Deezer track metadata.

    For each song with a deezer_id but no album link, fetches the track from
    Deezer to get the album_deezer_id, then links to existing Album records.
    Songs whose albums aren't in the database are skipped.

    Args:
        songs_per_task: Number of songs to process per task invocation.
        last_song_id: ID of the last song processed in the previous task.
    """
    import time

    from src.providers.deezer import DeezerMetadataProvider

    songs_without_album = list(
        Song.objects.filter(
            album__isnull=True,
            deezer_id__isnull=False,
            id__gt=last_song_id,
        )
        .order_by("id")
        .values_list("id", "deezer_id")[:songs_per_task]
    )

    if not songs_without_album:
        total_no_deezer = Song.objects.filter(
            album__isnull=True, deezer_id__isnull=True
        ).count()
        if total_no_deezer > 0:
            logger.info(
                f"Album backfill complete - {total_no_deezer} songs remain "
                f"unlinked (no deezer_id)"
            )
        else:
            logger.info("Album backfill complete - no more songs without album link")
        return

    max_song_id = songs_without_album[-1][0]

    logger.info(
        f"Backfilling album links for {len(songs_without_album)} songs via Deezer"
    )

    try:
        provider = DeezerMetadataProvider()
        album_cache: dict[int, Album | None] = {}
        song_album_pairs: list[tuple[int, int]] = []
        total_no_album_data = 0
        total_album_not_found = 0

        for song_id, deezer_id in songs_without_album:
            track = provider.get_track(deezer_id)
            if not track or not track.album_deezer_id:
                total_no_album_data += 1
                time.sleep(0.1)
                continue

            album_deezer_id = track.album_deezer_id

            if album_deezer_id not in album_cache:
                album_cache[album_deezer_id] = Album.objects.filter(
                    deezer_id=album_deezer_id
                ).first()

            if album_cache[album_deezer_id] is not None:
                song_album_pairs.append((song_id, album_deezer_id))
            else:
                total_album_not_found += 1

            time.sleep(0.1)

        total_linked = 0
        skipped_wrong_artist = 0
        if song_album_pairs:
            song_objs = list(
                Song.objects.filter(id__in=[s[0] for s in song_album_pairs])
            )
            pair_map = dict(song_album_pairs)
            songs_to_update = []
            for song in song_objs:
                album_deezer_id = pair_map[song.id]
                album = album_cache[album_deezer_id]
                a_aid = album.artist_id  # type: ignore[union-attr]
                s_aid = song.primary_artist_id  # type: ignore[attr-defined]
                if a_aid != s_aid:
                    skipped_wrong_artist += 1
                    continue
                song.album = album
                songs_to_update.append(song)
            if songs_to_update:
                Song.objects.bulk_update(songs_to_update, ["album"])
            total_linked = len(songs_to_update)

        logger.info(
            f"Linked {total_linked}/{len(songs_without_album)} songs to albums "
            f"({total_album_not_found} albums not in DB, "
            f"{total_no_album_data} tracks had no album data on Deezer, "
            f"{skipped_wrong_artist} skipped artist mismatch)"
        )

        remaining_after = Song.objects.filter(
            album__isnull=True, deezer_id__isnull=False, id__gt=max_song_id
        ).count()

        if remaining_after > 0:
            logger.info(
                f"{remaining_after} songs still need album link, scheduling next batch"
            )
            backfill_song_album.apply_async(
                kwargs={
                    "songs_per_task": songs_per_task,
                    "last_song_id": max_song_id,
                },
                countdown=30,
            )
        else:
            total_unlinked = Song.objects.filter(album__isnull=True).count()
            if total_unlinked > 0:
                logger.info(
                    f"Album backfill complete - {total_unlinked} songs remain "
                    f"unlinked (no deezer_id or albums not in database)"
                )
            else:
                logger.info("Album backfill complete - all songs linked to albums")

    except Exception as e:
        logger.error(f"Error during album backfill: {e}", exc_info=True)
        raise


@celery_app.task(
    bind=True,
    name="library_manager.tasks.cleanup_appears_on_albums",
)
def cleanup_appears_on_albums(self: Any) -> None:
    """Delete empty appears_on albums and unwant ones with songs.

    Spotify's API created thousands of 'appears_on' compilation albums
    (e.g. "100 Greatest Summer Songs") per artist. These are excluded
    from downloads by ALBUM_GROUPS_TO_IGNORE but still bloat the DB.

    This task:
    1. Deletes appears_on albums that have zero songs
    2. Sets wanted=False on appears_on albums that have songs
    """
    from django.db.models import Count

    task_history = create_task_history(
        task_id=self.request.id,
        task_type="MAINTENANCE",
        entity_type="SYSTEM",
        task_name="cleanup_appears_on_albums",
    )
    task_history.status = "RUNNING"
    task_history.save()

    try:
        appears_on = Album.objects.filter(album_group="appears_on")
        total = appears_on.count()

        if total == 0:
            msg = "No appears_on albums found"
            logger.info(msg)
            update_task_progress(task_history, 100.0, msg)
            complete_task(task_history)
            return

        update_task_progress(task_history, 0.0, f"Found {total} appears_on albums")

        # Split into empty vs has-songs
        annotated = appears_on.annotate(song_count=Count("songs"))
        empty = annotated.filter(song_count=0)
        with_songs = annotated.filter(song_count__gt=0)

        empty_count = empty.count()
        with_songs_count = with_songs.count()

        update_task_progress(
            task_history,
            20.0,
            f"{empty_count} empty, {with_songs_count} with songs",
        )

        # Delete empty albums (no songs, never downloadable)
        if empty_count > 0:
            deleted_count, _ = empty.delete()
            logger.info(f"Deleted {deleted_count} empty appears_on albums")
        else:
            deleted_count = 0

        update_task_progress(
            task_history, 70.0, f"Deleted {deleted_count} empty albums"
        )

        # Unwant albums that have songs (keep data, stop showing as undownloaded)
        unwanted_count = 0
        if with_songs_count > 0:
            unwanted_count = with_songs.filter(wanted=True).update(wanted=False)
            logger.info(
                f"Set wanted=False on {unwanted_count} appears_on albums with songs"
            )

        summary = (
            f"Cleaned up appears_on albums: {deleted_count} deleted (empty), "
            f"{unwanted_count} unwanted (had songs), {total} total processed"
        )
        logger.info(summary)
        update_task_progress(task_history, 100.0, summary)
        complete_task(task_history)

    except Exception as e:
        logger.exception(f"Error cleaning up appears_on albums: {e}")
        complete_task(task_history, success=False, error_message=str(e))
        raise


@celery_app.task(
    bind=True,
    name="library_manager.tasks.backfill_album_tracks",
)
def backfill_album_tracks(
    self: Any, batch_size: int = 200, last_album_id: int = 0
) -> None:
    """Re-fetch tracks for Deezer albums that have 0 songs.

    These albums were created during migration but their track fetch
    silently failed. Processes in batches, self-chaining until complete.
    """
    from django.db.models import Count, F

    from src.providers.deezer import DeezerMetadataProvider

    from .migration import _link_or_create_song

    task_history = create_task_history(
        task_id=self.request.id,
        task_type="MAINTENANCE",
        entity_type="SYSTEM",
        task_name="backfill_album_tracks",
    )
    task_history.status = "RUNNING"
    task_history.save()

    try:
        albums = list(
            Album.objects.filter(
                deezer_id__isnull=False,
                id__gt=last_album_id,
                spotify_gid__isnull=True,
            )
            .annotate(song_count=Count("songs"))
            .filter(song_count__lt=F("total_tracks"))
            .select_related("artist")
            .order_by("id")[:batch_size]
        )

        if not albums:
            msg = "No more albums need track backfill"
            logger.info(msg)
            update_task_progress(task_history, 100.0, msg)
            complete_task(task_history)
            return

        total_remaining = (
            Album.objects.filter(
                deezer_id__isnull=False,
                id__gt=last_album_id,
                spotify_gid__isnull=True,
            )
            .annotate(song_count=Count("songs"))
            .filter(song_count__lt=F("total_tracks"))
            .count()
        )

        update_task_progress(
            task_history,
            0.0,
            f"Backfilling {len(albums)} albums ({total_remaining} remaining)",
        )

        provider = DeezerMetadataProvider()
        albums_filled = 0
        albums_empty = 0
        albums_errored = 0
        songs_created = 0
        max_album_id = albums[-1].id

        for idx, album in enumerate(albums):
            try:
                deezer_tracks = provider.get_album_tracks(album.deezer_id)
            except Exception as e:
                logger.debug(
                    f"backfill_album_tracks: failed for '{album.name}' "
                    f"(deezer_id={album.deezer_id}): {e}"
                )
                albums_errored += 1
                # API error + no songs = album likely removed from Deezer.
                # Delete it rather than leaving a dead shell.
                if Song.objects.filter(album=album).count() == 0:
                    logger.info(
                        "Deleting dead album '%s' (deezer_id=%d): "
                        "API error and 0 songs",
                        album.name,
                        album.deezer_id,
                    )
                    album.delete()
                continue

            if not deezer_tracks:
                albums_empty += 1
                # Deezer returned empty track list + no songs in DB = dead album
                if Song.objects.filter(album=album).count() == 0:
                    logger.info(
                        "Deleting empty album '%s' (deezer_id=%d): "
                        "0 tracks on Deezer and 0 songs in DB",
                        album.name,
                        album.deezer_id,
                    )
                    album.delete()
                continue

            # Update total_tracks from actual count
            if album.total_tracks == 0:
                album.total_tracks = len(deezer_tracks)
                album.save(update_fields=["total_tracks"])

            album_songs_added = 0
            for track in deezer_tracks:
                result = _link_or_create_song(
                    track, album.artist, album  # type: ignore[arg-type]
                )
                if result in ("linked", "created"):
                    album_songs_added += 1

            songs_created += album_songs_added
            if album_songs_added > 0:
                albums_filled += 1
            elif deezer_tracks:
                # All tracks already exist elsewhere — sync total_tracks
                # to actual song count so this album won't be reprocessed
                actual = Song.objects.filter(album=album).count()
                if album.total_tracks != actual:
                    album.total_tracks = actual
                    album.save(update_fields=["total_tracks"])

            if (idx + 1) % 50 == 0:
                progress = 100.0 * (idx + 1) / len(albums)
                update_task_progress(
                    task_history,
                    progress,
                    f"Processed {idx + 1}/{len(albums)}: "
                    f"{albums_filled} filled, {songs_created} songs",
                )

        summary = (
            f"Backfilled {len(albums)} albums: "
            f"{albums_filled} filled ({songs_created} songs), "
            f"{albums_empty} empty on Deezer, {albums_errored} API errors"
        )
        logger.info(summary)
        update_task_progress(task_history, 100.0, summary)
        complete_task(task_history)

        # Self-chain for next batch
        next_remaining = (
            Album.objects.filter(
                deezer_id__isnull=False,
                id__gt=max_album_id,
                spotify_gid__isnull=True,
            )
            .annotate(song_count=Count("songs"))
            .filter(song_count__lt=F("total_tracks"))
            .count()
        )
        if next_remaining > 0:
            logger.info(
                f"{next_remaining} albums still need backfill, scheduling next batch"
            )
            backfill_album_tracks.apply_async(
                kwargs={
                    "batch_size": batch_size,
                    "last_album_id": max_album_id,
                },
            )

    except Exception as e:
        logger.exception(f"Error in backfill_album_tracks: {e}")
        complete_task(task_history, success=False, error_message=str(e))
        raise


@celery_app.task(
    bind=True,
    name="library_manager.tasks.cleanup_orphaned_albums",
)
def cleanup_orphaned_albums(self: Any) -> None:
    """Clean up albums with bad names, stale states, and Spotify-only empties.

    Handles:
    1. Albums with bad names ("missing", "Unknown", "None", "null", "N/A")
       that have 0 songs — deleted
    2. Empty albums marked downloaded=True — reset to downloaded=False
    3. Spotify-only empty albums (no deezer_id, 0 songs) — deleted in batches
    4. "missing" albums with songs that are misattributed compilations — unwanted
    """
    from django.db.models import Count

    task_history = create_task_history(
        task_id=self.request.id,
        task_type="MAINTENANCE",
        entity_type="SYSTEM",
        task_name="cleanup_orphaned_albums",
    )
    task_history.status = "RUNNING"
    task_history.save()

    try:
        stats: dict[str, int] = {}

        # 1. Delete empty albums with bad names
        bad_names = ["missing", "Unknown", "None", "null", "N/A"]
        bad_name_deleted = 0
        for name in bad_names:
            qs = (
                Album.objects.filter(name=name)
                .annotate(song_count=Count("songs"))
                .filter(song_count=0)
            )
            count = qs.count()
            if count > 0:
                qs.delete()
                bad_name_deleted += count
                logger.info(f"Deleted {count} empty albums named '{name}'")
        stats["bad_name_empty_deleted"] = bad_name_deleted

        update_task_progress(
            task_history,
            10.0,
            f"Deleted {bad_name_deleted} empty bad-name albums",
        )

        # 2. Unwant "missing" albums that have songs (misattributed compilations)
        missing_with_songs = (
            Album.objects.filter(name="missing")
            .annotate(song_count=Count("songs"))
            .filter(song_count__gt=0, wanted=True)
        )
        unwanted_count = missing_with_songs.update(wanted=False)
        stats["missing_unwanted"] = unwanted_count
        if unwanted_count:
            logger.info(
                f"Set wanted=False on {unwanted_count} 'missing' albums with songs"
            )

        update_task_progress(
            task_history, 20.0, f"Unwanted {unwanted_count} compilations"
        )

        # 3. Fix empty albums marked as downloaded (ghost albums)
        # Only reset Deezer albums — Spotify-only empties can't be
        # downloaded via the Deezer pipeline.
        empty_downloaded = (
            Album.objects.filter(downloaded=True, deezer_id__isnull=False)
            .annotate(song_count=Count("songs"))
            .filter(song_count=0)
        )
        reset_count = empty_downloaded.update(downloaded=False, failed_count=0)
        stats["empty_downloaded_reset"] = reset_count
        if reset_count:
            logger.info(
                f"Reset {reset_count} empty Deezer albums from "
                f"downloaded=True for re-download"
            )

        update_task_progress(
            task_history, 30.0, f"Reset {reset_count} ghost albums for re-download"
        )

        # 4. Delete Spotify-only empty albums (no deezer_id, 0 songs)
        # These are stubs from old Spotify sync that will never get tracks.
        # Delete in batches to avoid long-running queries.
        spotify_empty = (
            Album.objects.filter(
                spotify_gid__isnull=False,
                deezer_id__isnull=True,
            )
            .annotate(song_count=Count("songs"))
            .filter(song_count=0)
        )
        spotify_empty_total = spotify_empty.count()
        spotify_deleted = 0

        update_task_progress(
            task_history,
            35.0,
            f"Found {spotify_empty_total} Spotify-only empty albums to delete",
        )

        batch_size = 5000
        while True:
            batch_ids = list(
                Album.objects.filter(
                    spotify_gid__isnull=False,
                    deezer_id__isnull=True,
                )
                .annotate(song_count=Count("songs"))
                .filter(song_count=0)
                .values_list("id", flat=True)[:batch_size]
            )
            if not batch_ids:
                break
            deleted_count, _ = Album.objects.filter(id__in=batch_ids).delete()
            spotify_deleted += deleted_count

            if spotify_empty_total > 0:
                progress = 35.0 + (60.0 * spotify_deleted / spotify_empty_total)
                update_task_progress(
                    task_history,
                    min(progress, 95.0),
                    f"Deleted {spotify_deleted}/{spotify_empty_total} Spotify-only empties",
                )

        stats["spotify_empty_deleted"] = spotify_deleted
        logger.info(f"Deleted {spotify_deleted} Spotify-only empty albums")

        summary = (
            f"Album cleanup complete: "
            f"{bad_name_deleted} bad-name deleted, "
            f"{unwanted_count} compilations unwanted, "
            f"{reset_count} empty-downloaded reset, "
            f"{spotify_deleted} Spotify-only empties deleted"
        )
        logger.info(summary)
        update_task_progress(task_history, 100.0, summary)
        complete_task(task_history)

    except Exception as e:
        logger.exception(f"Error in cleanup_orphaned_albums: {e}")
        complete_task(task_history, success=False, error_message=str(e))
        raise


def _find_correct_album_via_deezer(
    provider: Any,
    song: Song,
    correct_artist_id: int,
    cache: dict[tuple[int, int], Optional[Album]],
) -> Optional[Album]:
    """Ask Deezer which album a track belongs to, filtered by artist."""
    import time

    if not song.deezer_id:
        return None

    try:
        track = provider.get_track(song.deezer_id)
        if not track or not track.album_deezer_id:
            return None

        deezer_key = (track.album_deezer_id, correct_artist_id)
        if deezer_key not in cache:
            cache[deezer_key] = Album.objects.filter(
                deezer_id=track.album_deezer_id,
                artist_id=correct_artist_id,
            ).first()
        return cache[deezer_key]
    except Exception as e:
        logger.debug(f"Deezer lookup failed for song {song.id}: {e}")
        return None
    finally:
        time.sleep(0.1)


@celery_app.task(
    bind=True,
    name="library_manager.tasks.repair_misassigned_songs",
)
def repair_misassigned_songs(
    self: Any, batch_size: int = 500, last_song_id: int = 0
) -> None:
    """Fix songs assigned to albums belonging to a different artist.

    Finds songs where primary_artist_id != album.artist_id (cross-artist
    contamination from backfill_song_album not validating artist match).

    For each misassigned song:
    1. Try to find an album by the correct artist with the same name
    2. If not found and song has deezer_id, ask Deezer for the correct album
    3. If still not found, set album=None

    Self-chains until all misassigned songs are processed.
    """
    from django.db.models import F

    task_history = create_task_history(
        task_id=self.request.id,
        task_type="MAINTENANCE",
        entity_type="SYSTEM",
        task_name="repair_misassigned_songs",
    )
    task_history.status = "RUNNING"
    task_history.save()

    try:
        misassigned = list(
            Song.objects.filter(
                album__isnull=False,
                id__gt=last_song_id,
            )
            .exclude(primary_artist_id=F("album__artist_id"))
            .select_related("album")
            .order_by("id")[:batch_size]
        )

        if not misassigned:
            msg = "No more misassigned songs to repair"
            logger.info(msg)
            update_task_progress(task_history, 100.0, msg)
            complete_task(task_history)
            return

        total_remaining = (
            Song.objects.filter(album__isnull=False, id__gt=last_song_id)
            .exclude(primary_artist_id=F("album__artist_id"))
            .count()
        )

        update_task_progress(
            task_history,
            0.0,
            f"Repairing {len(misassigned)} songs ({total_remaining} remaining)",
        )

        from src.providers.deezer import DeezerMetadataProvider

        provider = DeezerMetadataProvider()
        reassigned_by_name = 0
        reassigned_by_api = 0
        nulled = 0
        max_song_id = misassigned[-1].id

        # Cache: (artist_id, album_name) -> Album or None
        album_name_cache: dict[tuple[int, str], Optional[Album]] = {}
        # Cache: (deezer_album_id, artist_id) -> Album or None
        album_deezer_cache: dict[tuple[int, int], Optional[Album]] = {}

        for idx, song in enumerate(misassigned):
            wrong_album: Album = song.album  # type: ignore[assignment]
            correct_artist_id: int = song.primary_artist_id  # type: ignore[attr-defined]

            # Strategy 1: Same-name album by the correct artist
            name_key: tuple[int, str] = (correct_artist_id, wrong_album.name)
            if name_key not in album_name_cache:
                album_name_cache[name_key] = Album.objects.filter(
                    artist_id=correct_artist_id,
                    name=wrong_album.name,
                ).first()

            correct_album = album_name_cache[name_key]

            if correct_album:
                song.album = correct_album
                song.save(update_fields=["album_id"])
                reassigned_by_name += 1
                continue

            # Strategy 2: Deezer API lookup
            correct_album = _find_correct_album_via_deezer(
                provider, song, correct_artist_id, album_deezer_cache
            )
            if correct_album:
                song.album = correct_album
                song.save(update_fields=["album_id"])
                reassigned_by_api += 1
                continue

            # Strategy 3: Null out the album
            song.album = None
            song.save(update_fields=["album_id"])
            nulled += 1

            if (idx + 1) % 100 == 0:
                progress = 100.0 * (idx + 1) / len(misassigned)
                update_task_progress(
                    task_history,
                    progress,
                    f"Processed {idx + 1}/{len(misassigned)}: "
                    f"{reassigned_by_name} by name, "
                    f"{reassigned_by_api} by API, {nulled} nulled",
                )

        summary = (
            f"Repaired {len(misassigned)} misassigned songs: "
            f"{reassigned_by_name} reassigned by name, "
            f"{reassigned_by_api} reassigned by API, "
            f"{nulled} album nulled"
        )
        logger.info(summary)
        update_task_progress(task_history, 100.0, summary)
        complete_task(task_history)

        # Self-chain for next batch
        next_remaining = (
            Song.objects.filter(album__isnull=False, id__gt=max_song_id)
            .exclude(primary_artist_id=F("album__artist_id"))
            .count()
        )
        if next_remaining > 0:
            logger.info(
                f"{next_remaining} misassigned songs remaining, "
                f"scheduling next batch"
            )
            repair_misassigned_songs.apply_async(
                kwargs={
                    "batch_size": batch_size,
                    "last_song_id": max_song_id,
                },
                countdown=5,
            )

    except Exception as e:
        logger.exception(f"Error in repair_misassigned_songs: {e}")
        complete_task(task_history, success=False, error_message=str(e))
        raise


@celery_app.task(
    bind=True,
    name="library_manager.tasks.merge_duplicate_songs",
)
def merge_duplicate_songs(
    self: Any, batch_size: int = 500, last_song_id: int = 0
) -> None:
    """Merge albumless duplicate songs into their with-album counterparts.

    Finds songs where: album is NULL, has ISRC, and another song with the
    same ISRC exists with an album. The with-album copy is kept as the
    target; the albumless copy's download data, Spotify GID, and other
    fields are merged into it using the existing _merge_song logic.

    Self-chains until all duplicates are processed.
    """
    from django.db import transaction

    from library_manager.management.commands.merge_duplicate_artists import (
        _merge_song,
    )

    task_history = create_task_history(
        task_id=self.request.id,
        task_type="MAINTENANCE",
        entity_type="SYSTEM",
        task_name="merge_duplicate_songs",
    )
    task_history.status = "RUNNING"
    task_history.save()

    try:
        # ISRCs that have both an albumless and a with-album song
        with_album_isrcs = (
            Song.objects.filter(isrc__isnull=False, album__isnull=False)
            .values_list("isrc", flat=True)
            .distinct()
        )

        albumless_dupes = list(
            Song.objects.filter(
                isrc__isnull=False,
                album__isnull=True,
                id__gt=last_song_id,
                isrc__in=with_album_isrcs,
            )
            .select_related("primary_artist")
            .order_by("id")[:batch_size]
        )

        if not albumless_dupes:
            msg = "No more duplicate songs to merge"
            logger.info(msg)
            update_task_progress(task_history, 100.0, msg)
            complete_task(task_history)
            return

        total_remaining = Song.objects.filter(
            isrc__isnull=False,
            album__isnull=True,
            id__gt=last_song_id,
            isrc__in=with_album_isrcs,
        ).count()

        update_task_progress(
            task_history,
            0.0,
            f"Merging {len(albumless_dupes)} duplicates ({total_remaining} remaining)",
        )

        merged = 0
        skipped = 0
        max_song_id = albumless_dupes[-1].id

        for idx, albumless_song in enumerate(albumless_dupes):
            target = Song.objects.filter(
                isrc=albumless_song.isrc,
                album__isnull=False,
                primary_artist=albumless_song.primary_artist,
            ).first()

            if not target:
                # Different artist or target disappeared — skip
                skipped += 1
                continue

            with transaction.atomic():
                _merge_song(albumless_song, target)
            merged += 1

            if (idx + 1) % 100 == 0:
                progress = 100.0 * (idx + 1) / len(albumless_dupes)
                update_task_progress(
                    task_history,
                    progress,
                    f"Processed {idx + 1}/{len(albumless_dupes)}: "
                    f"{merged} merged, {skipped} skipped",
                )

        summary = (
            f"Merged {merged} duplicate songs, skipped {skipped} "
            f"(of {len(albumless_dupes)} in batch)"
        )
        logger.info(summary)
        update_task_progress(task_history, 100.0, summary)
        complete_task(task_history)

        # Self-chain for next batch
        next_remaining = Song.objects.filter(
            isrc__isnull=False,
            album__isnull=True,
            id__gt=max_song_id,
            isrc__in=with_album_isrcs,
        ).count()
        if next_remaining > 0:
            logger.info(
                f"{next_remaining} duplicate songs remaining, " f"scheduling next batch"
            )
            merge_duplicate_songs.apply_async(
                kwargs={
                    "batch_size": batch_size,
                    "last_song_id": max_song_id,
                },
                countdown=5,
            )

    except Exception as e:
        logger.exception(f"Error in merge_duplicate_songs: {e}")
        complete_task(task_history, success=False, error_message=str(e))
        raise


@celery_app.task(
    bind=True,
    name="library_manager.tasks.backfill_lyrics_status",
)
def backfill_lyrics_status(self: Any, batch_size: int = 500) -> None:
    """Scan downloaded songs and create SongLyricsStatus records.

    For each downloaded song with a file_path_ref:
    - If an .lrc file exists on disk (exact or fuzzy match), mark has_lyrics=True
    - If no .lrc file, mark has_lyrics=False (queued for retry)

    Idempotent — skips songs that already have a SongLyricsStatus record.
    """
    from pathlib import Path

    from downloader.lyrics import find_existing_lrc

    from ..models import SongLyricsStatus

    task_history = create_task_history(
        task_id=self.request.id,
        task_type="MAINTENANCE",
        entity_type="SYSTEM",
        task_name="backfill_lyrics_status",
    )
    task_history.status = "RUNNING"
    task_history.save()

    try:
        songs = (
            Song.objects.filter(
                downloaded=True,
                file_path_ref__isnull=False,
            )
            .exclude(lyrics_status__isnull=False)
            .select_related("file_path_ref", "primary_artist")
            .order_by("-primary_artist__tracking_tier", "id")[:batch_size]
        )

        total_remaining = (
            Song.objects.filter(
                downloaded=True,
                file_path_ref__isnull=False,
            )
            .exclude(lyrics_status__isnull=False)
            .count()
        )

        if not songs.exists():
            msg = "No more songs need lyrics status backfill"
            logger.info(msg)
            update_task_progress(task_history, 100.0, msg)
            complete_task(task_history)
            return

        update_task_progress(
            task_history,
            0.0,
            f"Scanning {len(songs)} songs ({total_remaining} remaining)",
        )

        has_lyrics_count = 0
        missing_count = 0
        statuses_to_create: list[SongLyricsStatus] = []

        for idx, song in enumerate(songs):
            if not song.file_path_ref:
                continue
            audio_path = Path(song.file_path_ref.path)  # type: ignore[attr-defined]
            existing_lrc = find_existing_lrc(audio_path)

            # Rename misnamed .lrc to match the audio file so media players find it
            if existing_lrc is not None:
                correct_lrc = audio_path.with_suffix(".lrc")
                if existing_lrc != correct_lrc:
                    try:
                        existing_lrc.rename(correct_lrc)
                    except OSError:
                        pass

            statuses_to_create.append(
                SongLyricsStatus(
                    song=song,
                    has_lyrics=existing_lrc is not None,
                    attempt_count=0,
                )
            )
            if existing_lrc:
                has_lyrics_count += 1
            else:
                missing_count += 1

            if (idx + 1) % 100 == 0:
                progress = 100.0 * (idx + 1) / len(songs)
                update_task_progress(
                    task_history,
                    progress,
                    f"Scanned {idx + 1}/{len(songs)}: "
                    f"{has_lyrics_count} with lyrics, {missing_count} missing",
                )

        # Bulk create, ignoring any that already exist
        SongLyricsStatus.objects.bulk_create(statuses_to_create, ignore_conflicts=True)

        summary = (
            f"Backfilled {len(songs)} lyrics statuses: "
            f"{has_lyrics_count} with lyrics, {missing_count} missing"
        )
        logger.info(summary)
        update_task_progress(task_history, 100.0, summary)
        complete_task(task_history)

        # Self-chain if more remain
        next_remaining = (
            Song.objects.filter(
                downloaded=True,
                file_path_ref__isnull=False,
            )
            .exclude(lyrics_status__isnull=False)
            .count()
        )
        if next_remaining > 0:
            logger.info(
                f"{next_remaining} songs still need lyrics backfill, "
                f"scheduling next batch"
            )
            backfill_lyrics_status.apply_async(
                kwargs={"batch_size": batch_size},
                countdown=5,
            )

    except Exception as e:
        logger.exception(f"Error in backfill_lyrics_status: {e}")
        complete_task(task_history, success=False, error_message=str(e))
        raise
