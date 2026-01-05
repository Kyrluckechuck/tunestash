"""Maintenance tasks for the Spotify library manager."""

from typing import Any, Optional

from celery_app import app as celery_app
from downloader.spotdl_wrapper import YouTubeRateLimitError
from downloader.spotipy_tasks import SpotifyRateLimitError
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
    # Note: Don't self-queue - let Celery Beat handle scheduling to avoid infinite loops


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

        song_uris = [song.spotify_uri for song in failed_songs]

        downloader_config = Config(urls=song_uris, track_artists=False)

        def task_callback(progress_pct: float, message: str) -> None:
            update_task_progress(task_history, 25.0 + (progress_pct * 0.70), message)

        logger.info(f"Retrying {song_count} failed songs for artist {artist.name}")
        spotdl_wrapper.execute(downloader_config, task_callback)

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
    self: Any, batches_per_task: int = 5, last_song_id: int = 0
) -> None:
    """
    Backfill ISRC codes for existing songs that don't have them.

    Uses Spotify's batch track endpoint to fetch up to 50 tracks per API call.
    Processes multiple batches per task to reduce Celery overhead, then chains
    to the next task until all songs are processed.

    Args:
        batches_per_task: Number of 50-track API batches to process per task.
                         Default 5 = 250 songs per task invocation.
        last_song_id: ID of the last song processed in the previous task.
                      Used for pagination to avoid re-querying songs without ISRC.
    """
    import time

    from downloader.spotipy_tasks import PublicSpotifyClient

    spotify_batch_size = 50  # Spotify API limit
    songs_per_task = spotify_batch_size * batches_per_task

    # Find songs without ISRC, ordered by ID for consistent pagination
    # Filter by id > last_song_id to skip songs we've already attempted
    songs_without_isrc = list(
        Song.objects.filter(isrc__isnull=True, id__gt=last_song_id)
        .order_by("id")
        .values_list("id", "gid")[:songs_per_task]
    )

    if not songs_without_isrc:
        logger.info("ISRC backfill complete - no more songs without ISRC")
        return

    # Extract just the GIDs for API calls, track max ID for pagination
    song_gids = [gid for _, gid in songs_without_isrc]
    max_song_id = songs_without_isrc[-1][0]  # Last (highest) song ID in batch

    logger.info(
        f"Backfilling ISRC for {len(song_gids)} songs "
        f"({batches_per_task} batches of {spotify_batch_size})"
    )

    try:
        public_client = PublicSpotifyClient()
        if public_client.sp is None:
            logger.error("Failed to initialize Spotify client")
            return

        total_updated = 0
        total_no_isrc = 0

        # Process in batches of 50 (Spotify's limit)
        for batch_num in range(0, len(song_gids), spotify_batch_size):
            batch_gids = song_gids[batch_num : batch_num + spotify_batch_size]

            # Fetch tracks from Spotify
            result = public_client.sp.tracks(batch_gids)
            if not result or "tracks" not in result:
                logger.warning(
                    f"No results for batch {batch_num // spotify_batch_size + 1}"
                )
                continue

            # Build a map of gid -> isrc
            isrc_map = {}
            for track in result["tracks"]:
                if track and track.get("id"):
                    isrc = track.get("external_ids", {}).get("isrc")
                    if isrc:
                        isrc_map[track["id"]] = isrc
                    else:
                        total_no_isrc += 1

            # Bulk update using Django ORM
            if isrc_map:
                songs_to_update = list(Song.objects.filter(gid__in=isrc_map.keys()))
                for song in songs_to_update:
                    song.isrc = isrc_map[song.gid]
                Song.objects.bulk_update(songs_to_update, ["isrc"])
                total_updated += len(songs_to_update)

            # Delay between API calls to respect rate limits
            if batch_num + spotify_batch_size < len(song_gids):
                time.sleep(0.5)

        logger.info(
            f"Updated {total_updated}/{len(song_gids)} songs with ISRC "
            f"({total_no_isrc} tracks had no ISRC in Spotify)"
        )

        # Check if there are more songs to process beyond our current position
        remaining_after = Song.objects.filter(
            isrc__isnull=True, id__gt=max_song_id
        ).count()

        if remaining_after > 0:
            logger.info(
                f"{remaining_after} songs still need ISRC, scheduling next batch"
            )
            # 30s cooldown between chained tasks to stay within Spotify rate limits
            backfill_song_isrc.apply_async(
                kwargs={
                    "batches_per_task": batches_per_task,
                    "last_song_id": max_song_id,
                },
                countdown=30,
            )
        else:
            # Log final stats
            total_without_isrc = Song.objects.filter(isrc__isnull=True).count()
            if total_without_isrc > 0:
                logger.info(
                    f"ISRC backfill complete - {total_without_isrc} songs remain "
                    f"without ISRC (not available in Spotify)"
                )
            else:
                logger.info("ISRC backfill complete - all songs have ISRC")

    except SpotifyRateLimitError as rate_limit_error:
        # Spotify rate limit - reschedule task for later
        retry_after = rate_limit_error.retry_after_seconds
        logger.warning(
            f"Spotify rate limit hit during ISRC backfill, "
            f"rescheduling in {retry_after}s"
        )
        raise self.retry(
            exc=rate_limit_error,
            countdown=retry_after,
            max_retries=10,  # Allow more retries since backfill may take a while
        )
    except Exception as e:
        logger.error(f"Error during ISRC backfill: {e}", exc_info=True)
        raise


@celery_app.task(bind=True, name="library_manager.tasks.backfill_song_album")
def backfill_song_album(
    self: Any, batches_per_task: int = 5, last_song_id: int = 0
) -> None:
    """
    Backfill album associations for existing songs that don't have them.

    Uses Spotify's batch track endpoint to fetch track metadata including album ID.
    Links songs to existing Album records in the database. Songs whose albums
    don't exist locally are skipped (they'll be linked when the album is synced).

    Args:
        batches_per_task: Number of 50-track API batches to process per task.
                         Default 5 = 250 songs per task invocation.
        last_song_id: ID of the last song processed in the previous task.
                      Used for pagination to avoid re-querying unlinkable songs.
    """
    import time

    from downloader.spotipy_tasks import PublicSpotifyClient

    spotify_batch_size = 50  # Spotify API limit
    songs_per_task = spotify_batch_size * batches_per_task

    # Find songs without album link, ordered by ID for consistent pagination
    # Filter by id > last_song_id to skip songs we've already attempted
    songs_without_album = list(
        Song.objects.filter(album__isnull=True, id__gt=last_song_id)
        .order_by("id")
        .values_list("id", "gid")[:songs_per_task]
    )

    if not songs_without_album:
        logger.info("Album backfill complete - no more songs without album link")
        return

    # Extract just the GIDs for API calls, track max ID for pagination
    song_gids = [gid for _, gid in songs_without_album]
    max_song_id = songs_without_album[-1][0]  # Last (highest) song ID in batch

    logger.info(
        f"Backfilling album links for {len(song_gids)} songs "
        f"({batches_per_task} batches of {spotify_batch_size})"
    )

    try:
        public_client = PublicSpotifyClient()
        if public_client.sp is None:
            logger.error("Failed to initialize Spotify client")
            return

        total_linked = 0
        total_album_not_found = 0
        total_no_album_data = 0

        # Build a cache of album GIDs to Album objects for this batch
        # This reduces repeated DB queries
        album_cache: dict[str, Album] = {}

        # Process in batches of 50 (Spotify's limit)
        for batch_num in range(0, len(song_gids), spotify_batch_size):
            batch_gids = song_gids[batch_num : batch_num + spotify_batch_size]

            # Fetch tracks from Spotify
            result = public_client.sp.tracks(batch_gids)
            if not result or "tracks" not in result:
                logger.warning(
                    f"No results for batch {batch_num // spotify_batch_size + 1}"
                )
                continue

            # Build a map of song_gid -> album_gid
            song_album_map: dict[str, str] = {}
            album_gids_needed: set[str] = set()

            for track in result["tracks"]:
                if not track or not track.get("id"):
                    continue
                album_gid = track.get("album", {}).get("id")
                if not album_gid:
                    total_no_album_data += 1
                    continue
                song_album_map[track["id"]] = album_gid
                if album_gid not in album_cache:
                    album_gids_needed.add(album_gid)

            # Bulk fetch albums we don't have cached yet
            if album_gids_needed:
                albums = Album.objects.filter(spotify_gid__in=album_gids_needed)
                for album in albums:
                    album_cache[album.spotify_gid] = album

            # Link songs to albums
            songs_to_update = []
            for song in Song.objects.filter(gid__in=song_album_map.keys()):
                album_gid = song_album_map.get(song.gid)
                if album_gid and album_gid in album_cache:
                    song.album = album_cache[album_gid]
                    songs_to_update.append(song)
                elif album_gid:
                    total_album_not_found += 1

            if songs_to_update:
                Song.objects.bulk_update(songs_to_update, ["album"])
                total_linked += len(songs_to_update)

            # Delay between API calls to respect rate limits
            if batch_num + spotify_batch_size < len(song_gids):
                time.sleep(0.5)

        logger.info(
            f"Linked {total_linked}/{len(song_gids)} songs to albums "
            f"({total_album_not_found} albums not in DB, "
            f"{total_no_album_data} tracks had no album data)"
        )

        # Check if there are more songs to process beyond our current position
        remaining_after = Song.objects.filter(
            album__isnull=True, id__gt=max_song_id
        ).count()

        if remaining_after > 0:
            logger.info(
                f"{remaining_after} songs still need album link, scheduling next batch"
            )
            # 30s cooldown between chained tasks to stay within Spotify rate limits
            backfill_song_album.apply_async(
                kwargs={
                    "batches_per_task": batches_per_task,
                    "last_song_id": max_song_id,
                },
                countdown=30,
            )
        else:
            # Log final stats
            total_unlinked = Song.objects.filter(album__isnull=True).count()
            if total_unlinked > 0:
                logger.info(
                    f"Album backfill complete - {total_unlinked} songs remain "
                    f"unlinked (their albums are not in the database)"
                )
            else:
                logger.info("Album backfill complete - all songs linked to albums")

    except SpotifyRateLimitError as rate_limit_error:
        # Spotify rate limit - reschedule task for later
        retry_after = rate_limit_error.retry_after_seconds
        logger.warning(
            f"Spotify rate limit hit during album backfill, "
            f"rescheduling in {retry_after}s"
        )
        raise self.retry(
            exc=rate_limit_error,
            countdown=retry_after,
            max_retries=10,  # Allow more retries since backfill may take a while
        )
    except Exception as e:
        logger.error(f"Error during album backfill: {e}", exc_info=True)
        raise
