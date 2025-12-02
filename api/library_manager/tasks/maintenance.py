"""Maintenance tasks for the Spotify library manager."""

from typing import Any, Optional

from celery_app import app as celery_app
from downloader.spotdl_wrapper import YouTubeRateLimitError
from lib.config_class import Config

from ..models import Song, TaskHistory
from .core import logger, require_download_capability, spotdl_wrapper


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

    failed_song_array = [
        song.spotify_uri for song in missing_known_songs_list.iterator()
    ]

    logger.info(f"Downloading {len(failed_song_array)} missing songs")
    downloader_config = Config(urls=failed_song_array, track_artists=False)

    # Create progress callback if task history is available
    task_progress_callback = None
    if hasattr(self, "request") and self.request.id:
        task_history = TaskHistory.objects.filter(task_id=self.request.id).first()
        if task_history:
            # Capture task_history in closure to avoid cell-var-from-loop
            captured_task_history = task_history

            def update_task_progress_callback(
                progress_pct: float, message: str
            ) -> None:
                captured_task_history.update_progress(progress_pct)

            task_progress_callback = update_task_progress_callback

    try:
        spotdl_wrapper.execute(downloader_config, task_progress_callback)
    except YouTubeRateLimitError as rate_limit_error:
        # YouTube rate limit - reschedule task for later
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

    # Queue up next batch after ensuring rate limit has passed
    retry_all_missing_known_songs.apply_async(countdown=30)


@celery_app.task(
    bind=True, name="library_manager.tasks.cleanup_stuck_tasks_periodic"
)  # Scheduled via Celery Beat - Every 5 minutes
def cleanup_stuck_tasks_periodic(self: Any) -> None:
    """Periodically clean up stuck tasks and stale artist references"""
    from library_manager.models import TaskHistory

    stuck_count = TaskHistory.cleanup_stuck_tasks()
    if stuck_count > 0:
        logger.info(f"Cleaned up {stuck_count} stuck task(s)")

    # Note: Celery task queue cleanup is handled by the task revocation above
    # Additional queue-level cleanup can be added here if needed


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

    # Mark these songs as being attempted now and build URI list in single pass
    song_ids = []
    missing_song_array = []
    for song in non_downloaded_songs.iterator():
        song_ids.append(song.id)
        missing_song_array.append(song.spotify_uri)

    Song.objects.filter(id__in=song_ids).update(last_download_attempt=timezone.now())

    logger.info(f"Downloading {len(missing_song_array)} missing songs")
    downloader_config = Config(urls=missing_song_array, track_artists=False)

    # Create progress callback if task history is available
    task_progress_callback = None
    if hasattr(self, "request") and self.request.id:
        task_history = TaskHistory.objects.filter(task_id=self.request.id).first()
        if task_history:
            # Capture task_history in closure to avoid cell-var-from-loop
            captured_task_history = task_history

            def update_task_progress_callback(
                progress_pct: float, message: str
            ) -> None:
                captured_task_history.update_progress(progress_pct)

            task_progress_callback = update_task_progress_callback

    try:
        spotdl_wrapper.execute(downloader_config, task_progress_callback)
    except YouTubeRateLimitError as rate_limit_error:
        # YouTube rate limit - reschedule task for later
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

        # Build list of Spotify URIs to retry
        song_uris = [song.spotify_uri for song in songs_to_retry]

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

        # Download the songs
        downloader_config = Config(urls=song_uris, track_artists=False)

        # Create progress callback if task history is available
        task_progress_callback = None
        if hasattr(self, "request") and self.request.id:
            task_history = TaskHistory.objects.filter(task_id=self.request.id).first()
            if task_history:
                # Capture task_history in closure to avoid cell-var-from-loop
                captured_task_history = task_history

                def update_task_progress_callback(
                    progress_pct: float, message: str
                ) -> None:
                    captured_task_history.update_progress(progress_pct)

                task_progress_callback = update_task_progress_callback

        logger.info(f"Starting download retry for {song_count} songs")
        spotdl_wrapper.execute(downloader_config, task_progress_callback)
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
