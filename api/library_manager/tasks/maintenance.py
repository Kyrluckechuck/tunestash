"""Maintenance tasks for the Spotify library manager."""

import asyncio
from typing import Any, Optional

from celery_app import app as celery_app
from downloader.spotdl_wrapper import YouTubeRateLimitError
from lib.config_class import Config

from ..models import Album, Artist, Song, TaskHistory
from .core import (
    complete_task,
    create_task_history,
    logger,
    require_download_capability,
    spotdl_wrapper,
    update_task_progress,
)


def _download_deezer_songs_via_fallback(songs: list[Song]) -> tuple[int, int]:
    """Download Deezer-only songs (no Spotify GID) via YouTube/Tidal/Qobuz fallback.

    Returns (downloaded_count, failed_count).
    """
    from downloader.providers.base import SpotifyTrackMetadata
    from downloader.providers.fallback import FallbackDownloader

    from ..models import DownloadProvider as DownloadProviderEnum

    provider_enum_map = {
        "youtube": DownloadProviderEnum.YOUTUBE,
        "tidal": DownloadProviderEnum.TIDAL,
        "qobuz": DownloadProviderEnum.QOBUZ,
    }

    downloader = FallbackDownloader(
        provider_order=["youtube", "tidal", "qobuz"],
    )

    downloaded = 0
    failed = 0

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        for song in songs:
            album_name = song.album.name if song.album else ""  # type: ignore[attr-defined]
            artist_name = song.primary_artist.name  # type: ignore[attr-defined]

            metadata = SpotifyTrackMetadata(
                spotify_id="",
                title=song.name,
                artist=artist_name,
                album=album_name,
                album_artist=artist_name,
                duration_ms=0,
                isrc=song.isrc,
            )

            result = loop.run_until_complete(downloader.download_track(metadata))

            if result.success and result.file_path:
                dl_provider = provider_enum_map.get(
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
    from ..models import SpotifyRateLimitState

    # Check rate limit before doing any work
    rate_status = SpotifyRateLimitState.get_status()
    if rate_status["is_rate_limited"]:
        seconds_remaining = rate_status.get("seconds_until_clear", 0) or 0
        logger.info(
            f"[RATE LIMIT] Skipping retry_all_missing_known_songs - "
            f"rate limited for {seconds_remaining}s"
        )
        return

    # Check authentication before proceeding with any DB queries
    require_download_capability()

    missing_known_songs_list = (
        Song.objects.filter(bitrate=0, unavailable=False)
        .order_by("created_at")
        .select_related("primary_artist")
        .filter(primary_artist__tracked=True)[:100]
    )
    failed_known_songs_list = Song.objects.filter(
        failed_count__gt=0, bitrate=0, unavailable=False
    ).order_by("created_at")[:100]
    # Combine results for iterating
    missing_known_songs_list = missing_known_songs_list | failed_known_songs_list

    if missing_known_songs_list.count() == 0:
        logger.info("All songs downloaded, exiting missing known song loop!")
        return

    # Split into Spotify and Deezer-only songs
    spotify_songs = []
    deezer_only_songs = []
    for song in missing_known_songs_list.iterator():
        if song.gid:
            spotify_songs.append(song)
        elif song.deezer_id:
            deezer_only_songs.append(song)
        else:
            logger.warning(f"Song {song.id} has no gid or deezer_id, skipping")

    # Spotify path
    if spotify_songs:
        failed_song_array = [s.spotify_uri for s in spotify_songs]
        logger.info(f"Downloading {len(failed_song_array)} missing Spotify songs")
        downloader_config = Config(urls=failed_song_array, track_artists=False)

        task_progress_callback = None
        if hasattr(self, "request") and self.request.id:
            task_history = TaskHistory.objects.filter(task_id=self.request.id).first()
            if task_history:
                captured_task_history = task_history

                def update_task_progress_callback(
                    progress_pct: float, message: str
                ) -> None:
                    captured_task_history.update_progress(progress_pct)

                task_progress_callback = update_task_progress_callback

        try:
            spotdl_wrapper.execute(downloader_config, task_progress_callback)
        except YouTubeRateLimitError as rate_limit_error:
            retry_after = rate_limit_error.retry_after_seconds
            logger.warning(
                f"YouTube rate limit hit during missing songs retry, "
                f"rescheduling in {retry_after}s"
            )
            raise self.retry(
                exc=rate_limit_error,
                countdown=retry_after,
                max_retries=3,
            )

    # Deezer path
    if deezer_only_songs:
        logger.info(
            f"Downloading {len(deezer_only_songs)} missing Deezer-only songs "
            f"via fallback providers"
        )
        downloaded, failed = _download_deezer_songs_via_fallback(deezer_only_songs)
        logger.info(
            f"Deezer-only missing songs: {downloaded} downloaded, {failed} failed"
        )


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

    # Split songs by provider: Spotify (have gid) vs Deezer-only
    song_ids = []
    spotify_songs = []
    deezer_only_songs = []
    for song in non_downloaded_songs.iterator():
        if song.gid:
            spotify_songs.append(song)
            song_ids.append(song.id)
        elif song.deezer_id:
            deezer_only_songs.append(song)
            song_ids.append(song.id)
        else:
            logger.warning(f"Song {song.id} has no gid or deezer_id, skipping")

    Song.objects.filter(id__in=song_ids).update(last_download_attempt=timezone.now())

    # Spotify path: batch download via spotdl
    if spotify_songs:
        missing_song_array = [s.spotify_uri for s in spotify_songs]
        logger.info(f"Downloading {len(missing_song_array)} missing Spotify songs")
        downloader_config = Config(urls=missing_song_array, track_artists=False)

        task_progress_callback = None
        if hasattr(self, "request") and self.request.id:
            task_history = TaskHistory.objects.filter(task_id=self.request.id).first()
            if task_history:
                captured_task_history = task_history

                def update_task_progress_callback(
                    progress_pct: float, message: str
                ) -> None:
                    captured_task_history.update_progress(progress_pct)

                task_progress_callback = update_task_progress_callback

        try:
            spotdl_wrapper.execute(downloader_config, task_progress_callback)
        except YouTubeRateLimitError as rate_limit_error:
            retry_after = rate_limit_error.retry_after_seconds
            logger.warning(
                f"YouTube rate limit hit during undownloaded songs validation, "
                f"rescheduling in {retry_after}s"
            )
            raise self.retry(
                exc=rate_limit_error,
                countdown=retry_after,
                max_retries=3,
            )

    # Deezer path: download via fallback providers
    if deezer_only_songs:
        logger.info(
            f"Downloading {len(deezer_only_songs)} missing Deezer-only songs "
            f"via fallback providers"
        )
        downloaded, failed = _download_deezer_songs_via_fallback(deezer_only_songs)
        logger.info(f"Deezer-only validation: {downloaded} downloaded, {failed} failed")

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

        # Split into Spotify and Deezer-only songs
        spotify_songs = []
        deezer_only_songs = []
        for s in songs_to_retry:
            if s.gid:
                spotify_songs.append(s)
            elif s.deezer_id:
                deezer_only_songs.append(s)
            else:
                logger.warning(f"Song {s.id} has no gid or deezer_id, skipping")

        # Spotify path: batch retry via spotdl
        if spotify_songs:
            song_uris = [song.spotify_uri for song in spotify_songs]
            downloader_config = Config(urls=song_uris, track_artists=False)

            task_progress_callback = None
            if hasattr(self, "request") and self.request.id:
                task_history = TaskHistory.objects.filter(
                    task_id=self.request.id
                ).first()
                if task_history:
                    captured_task_history = task_history

                    def update_task_progress_callback(
                        progress_pct: float, message: str
                    ) -> None:
                        captured_task_history.update_progress(progress_pct)

                    task_progress_callback = update_task_progress_callback

            logger.info(
                f"Starting download retry for {len(spotify_songs)} Spotify songs"
            )
            spotdl_wrapper.execute(downloader_config, task_progress_callback)

        # Deezer path: retry via fallback providers
        if deezer_only_songs:
            logger.info(
                f"Retrying {len(deezer_only_songs)} Deezer-only songs "
                f"via fallback providers"
            )
            downloaded, failed = _download_deezer_songs_via_fallback(deezer_only_songs)
            logger.info(f"Deezer-only retry: {downloaded} downloaded, {failed} failed")

        logger.info(f"Completed retry attempt for {song_count} songs")

    except YouTubeRateLimitError as rate_limit_error:
        # YouTube rate limit - reschedule task for later
        retry_after = rate_limit_error.retry_after_seconds
        logger.warning(
            f"YouTube rate limit hit during failed songs retry, "
            f"rescheduling in {retry_after}s"
        )
        raise self.retry(
            exc=rate_limit_error,
            countdown=retry_after,
            max_retries=3,
        )
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
            entity_id=artist.gid,
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

        # Split into Spotify and Deezer-only songs
        spotify_songs = []
        deezer_only_songs = []
        for s in failed_songs:
            if s.gid:
                spotify_songs.append(s)
            elif s.deezer_id:
                deezer_only_songs.append(s)
            else:
                logger.warning(f"Song {s.id} has no gid or deezer_id, skipping")

        # Spotify path
        if spotify_songs:
            song_uris = [song.spotify_uri for song in spotify_songs]
            downloader_config = Config(urls=song_uris, track_artists=False)

            def task_callback(progress_pct: float, message: str) -> None:
                update_task_progress(
                    task_history, 25.0 + (progress_pct * 0.50), message
                )

            logger.info(
                f"Retrying {len(spotify_songs)} Spotify songs for artist {artist.name}"
            )
            spotdl_wrapper.execute(downloader_config, task_callback)

        # Deezer path
        if deezer_only_songs:
            logger.info(
                f"Retrying {len(deezer_only_songs)} Deezer-only songs "
                f"for artist {artist.name}"
            )
            downloaded, failed = _download_deezer_songs_via_fallback(deezer_only_songs)
            logger.info(
                f"Deezer-only retry for {artist.name}: "
                f"{downloaded} downloaded, {failed} failed"
            )

        task_history.add_log_message(f"Retried {song_count} failed songs")
        complete_task(task_history, success=True)

    except YouTubeRateLimitError as rate_limit_error:
        if task_history:
            task_history.status = "FAILED"
            task_history.add_log_message(
                f"Rate limited - retry in {rate_limit_error.retry_after_seconds}s"
            )
            task_history.save()
        raise self.retry(
            exc=rate_limit_error,
            countdown=rate_limit_error.retry_after_seconds,
            max_retries=3,
        )
    except Exception as e:
        logger.error(f"Error retrying failed songs for artist {artist_id}: {e}")
        if task_history:
            task_history.status = "FAILED"
            task_history.add_log_message(str(e))
            task_history.save()
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
        if song_album_pairs:
            song_objs = list(
                Song.objects.filter(id__in=[s[0] for s in song_album_pairs])
            )
            pair_map = dict(song_album_pairs)
            for song in song_objs:
                album_deezer_id = pair_map[song.id]
                song.album = album_cache[album_deezer_id]
            Song.objects.bulk_update(song_objs, ["album"])
            total_linked = len(song_objs)

        logger.info(
            f"Linked {total_linked}/{len(songs_without_album)} songs to albums "
            f"({total_album_not_found} albums not in DB, "
            f"{total_no_album_data} tracks had no album data on Deezer)"
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
