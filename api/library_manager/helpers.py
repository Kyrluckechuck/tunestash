import hashlib
import logging
from typing import Dict, List, Optional

from django.db.models import QuerySet

from .models import Artist, TrackedPlaylist, TrackingTier
from .tasks.core import TaskPriority

logger = logging.getLogger(__name__)

# Celery Task Deduplication Utilities


def generate_task_id(task_name: str, *args, **kwargs) -> str:
    """
    Generate a deterministic task ID based on task name and arguments.

    This allows Celery to deduplicate tasks - if a task with the same ID
    is already queued or running, attempting to queue another will be ignored.

    Args:
        task_name: Name of the Celery task
        *args: Positional arguments to the task
        **kwargs: Keyword arguments to the task

    Returns:
        A unique, deterministic task ID string
    """
    # Create a stable string representation of args/kwargs
    arg_str = f"{task_name}:{args}:{sorted(kwargs.items())}"
    # Hash it to get a reasonable-length ID
    task_hash = hashlib.md5(arg_str.encode()).hexdigest()
    return f"{task_name}-{task_hash[:12]}"


def is_task_pending_or_running(task_id: str) -> tuple[bool, str]:
    """
    Check if a task with the given ID is currently pending or running.

    Checks both TaskResult (Celery's result backend) and TaskHistory (app tracking)
    to catch tasks at any stage of execution.

    If a task exists but is in a terminal state (SUCCESS, FAILURE, etc.), the old
    records are deleted to allow re-queuing with the same deterministic task ID.

    Args:
        task_id: The Celery task ID to check

    Returns:
        Tuple of (is_pending_or_running: bool, reason: str)
        - reason explains why it was considered pending/running, or empty if not
    """
    from django_celery_results.models import TaskResult

    from .models import TaskHistory

    # Active states that should block re-queuing
    task_result_active_states = {"PENDING", "STARTED", "RETRY"}
    task_history_active_states = {"PENDING", "RUNNING"}

    # Check TaskResult (Celery's result backend) - tracks tasks that have started
    try:
        task_result = TaskResult.objects.get(task_id=task_id)
        if task_result.status in task_result_active_states:
            return True, f"TaskResult.status={task_result.status}"
        # Terminal state - delete so we can re-queue with same task_id
        logger.info(
            f"[DEDUP] Clearing stale TaskResult for {task_id} "
            f"(status={task_result.status})"
        )
        task_result.delete()
    except TaskResult.DoesNotExist:
        pass

    # Check TaskHistory (app tracking) - tracks tasks from when they begin executing
    try:
        task_history = TaskHistory.objects.get(task_id=task_id)
        if task_history.status in task_history_active_states:
            return True, f"TaskHistory.status={task_history.status}"
        # Terminal state - delete so we can re-queue with same task_id
        logger.info(
            f"[DEDUP] Clearing stale TaskHistory for {task_id} "
            f"(status={task_history.status})"
        )
        task_history.delete()
    except TaskHistory.DoesNotExist:
        pass

    return False, ""


def update_tracked_artists_albums(
    already_enqueued_artists: List[int],
    artists_to_enqueue: List[Artist],
    priority: Optional[int] = None,
) -> None:
    # Local import to avoid circular import during module initialization
    from .tasks import fetch_all_albums_for_artist

    # Use background priority for artist sync if not specified
    effective_priority = priority if priority is not None else TaskPriority.ARTIST_SYNC

    for artist in artists_to_enqueue:
        # Use database ID for internal operations
        if artist.id in already_enqueued_artists:
            continue

        # Generate deterministic task ID for deduplication
        task_id = generate_task_id(
            "library_manager.tasks.fetch_all_albums_for_artist", artist.id
        )

        # Skip if task is already queued or running
        is_pending, reason = is_task_pending_or_running(task_id)
        if is_pending:
            logger.info(
                f"[DEDUP] Skipping fetch_all_albums_for_artist for artist {artist.id}: "
                f"task_id={task_id}, reason={reason}"
            )
            continue

        # Queue task asynchronously with deterministic ID for deduplication
        fetch_all_albums_for_artist.apply_async(
            args=[artist.id], task_id=task_id, priority=effective_priority
        )


def download_missing_tracked_artists(
    already_enqueued_artists: List[int],
    artists_to_enqueue: List[Artist],
    priority: Optional[int] = None,
) -> None:
    # Local import to avoid circular import during module initialization
    from .models import SpotifyRateLimitState
    from .tasks import download_missing_albums_for_artist

    # Check rate limit before queuing any tasks - prevents cascade failures
    rate_status = SpotifyRateLimitState.get_status()
    if rate_status["is_rate_limited"]:
        seconds_remaining = rate_status.get("seconds_until_clear", 0) or 0
        logger.warning(
            f"[RATE LIMIT] Skipping download_missing_tracked_artists - "
            f"Spotify rate limited for {seconds_remaining}s"
        )
        return

    # Use background priority for artist downloads if not specified
    effective_priority = (
        priority if priority is not None else TaskPriority.ARTIST_DOWNLOAD
    )

    for artist in artists_to_enqueue:
        # Use database ID for internal operations
        if artist.id in already_enqueued_artists:
            continue

        # Generate deterministic task ID for deduplication
        task_id = generate_task_id(
            "library_manager.tasks.download_missing_albums_for_artist",
            artist.id,
            delay=5,
        )

        # Skip if task is already queued or running
        is_pending, reason = is_task_pending_or_running(task_id)
        if is_pending:
            logger.info(
                f"[DEDUP] Skipping download_missing_albums_for_artist for artist {artist.id}: "
                f"task_id={task_id}, reason={reason}"
            )
            continue

        # Queue the task asynchronously with deterministic ID for deduplication
        download_missing_albums_for_artist.apply_async(
            args=[artist.id],
            kwargs={"delay": 5},
            task_id=task_id,
            priority=effective_priority,
        )


def download_non_enqueued_playlists(
    already_enqueued_playlists: List[str],
    playlists_to_enqueue: List[TrackedPlaylist],
    priority: Optional[int] = None,
) -> None:
    # Local import to avoid circular import during module initialization
    from .models import PlaylistStatus, SpotifyRateLimitState
    from .tasks import download_playlist, sync_deezer_playlist

    logger.info(
        f"[ENQUEUE] download_non_enqueued_playlists called with "
        f"{len(playlists_to_enqueue)} playlists, "
        f"{len(already_enqueued_playlists)} already enqueued"
    )

    # Use high priority for playlists if not specified
    effective_priority = (
        priority if priority is not None else TaskPriority.PLAYLIST_DOWNLOAD
    )

    # Check Spotify rate limit only once (only needed for Spotify playlists)
    spotify_rate_limited = False
    rate_status = SpotifyRateLimitState.get_status()
    if rate_status["is_rate_limited"]:
        spotify_rate_limited = True
        seconds_remaining = rate_status.get("seconds_until_clear", 0) or 0
        logger.warning(
            f"[ENQUEUE] Spotify rate limited for {seconds_remaining}s "
            f"(Deezer playlists will still be processed)"
        )

    for playlist in playlists_to_enqueue:
        logger.info(
            f"[ENQUEUE] Processing playlist: {playlist.name} (id={playlist.id}, "
            f"url={playlist.url}, status={playlist.status})"
        )

        if playlist.url in already_enqueued_playlists:
            logger.info(f"[ENQUEUE] SKIP: {playlist.name} - already in enqueued list")
            continue

        # Skip playlists with problematic statuses
        if playlist.status in (
            PlaylistStatus.SPOTIFY_API_RESTRICTED,
            PlaylistStatus.NOT_FOUND,
        ):
            logger.info(
                f"[ENQUEUE] SKIP: {playlist.name} - problematic status: {playlist.status}"
            )
            continue

        # Route by provider
        if playlist.provider == "deezer":
            task_id = generate_task_id(
                "library_manager.tasks.sync_deezer_playlist", playlist.id
            )
            is_pending, reason = is_task_pending_or_running(task_id)
            if is_pending:
                logger.info(
                    f"[DEDUP] Skipping sync_deezer_playlist for '{playlist.name}': "
                    f"task_id={task_id}, reason={reason}"
                )
                continue
            sync_deezer_playlist.apply_async(
                args=[playlist.id],
                task_id=task_id,
                priority=effective_priority,
            )
            logger.info(f"[ENQUEUE] Queued Deezer sync: {playlist.name}")
        else:
            # Spotify playlist — skip if rate limited
            if spotify_rate_limited:
                logger.info(f"[ENQUEUE] SKIP: {playlist.name} - Spotify rate limited")
                continue

            task_id = generate_task_id(
                "library_manager.tasks.download_playlist",
                playlist.url,
                tracked=playlist.auto_track_artists,
            )

            is_pending, reason = is_task_pending_or_running(task_id)
            if is_pending:
                logger.info(
                    f"[DEDUP] Skipping download_playlist for '{playlist.name}': "
                    f"task_id={task_id}, reason={reason}"
                )
                continue

            download_playlist.apply_async(
                kwargs={
                    "playlist_url": playlist.url,
                    "tracked": playlist.auto_track_artists,
                },
                task_id=task_id,
                priority=effective_priority,
            )
            logger.info(f"[ENQUEUE] Queued Spotify download: {playlist.name}")


def enqueue_playlists(
    playlists_to_enqueue: List[TrackedPlaylist], priority: Optional[int] = None
) -> None:
    download_non_enqueued_playlists([], playlists_to_enqueue, priority=priority)


def enqueue_fetch_all_albums_for_artists(
    artists: QuerySet[Artist], extra_args: Optional[dict] = None
) -> None:
    """Enqueue fetch_all_albums_for_artist task for multiple artists."""
    if extra_args is None:
        extra_args = {}

    # Track already enqueued artists to avoid duplicates
    already_enqueued_artists = set()

    for artist in artists:
        # Use database ID for internal operations
        if artist.id in already_enqueued_artists:
            continue
        already_enqueued_artists.add(artist.id)

        # Pass database ID, not gid
        from .tasks import fetch_all_albums_for_artist

        # fetch_all_albums_for_artist doesn't accept any extra parameters
        fetch_all_albums_for_artist.delay(artist.id)


def enqueue_download_missing_albums_for_artists(
    artists: QuerySet[Artist], extra_args: Optional[dict] = None
) -> None:
    """Enqueue download_missing_albums_for_artist task for multiple artists."""
    if extra_args is None:
        extra_args = {}

    # Track already enqueued artists to avoid duplicates
    already_enqueued_artists = set()

    for artist in artists:
        # Use database ID for internal operations
        if artist.id in already_enqueued_artists:
            continue
        already_enqueued_artists.add(artist.id)

        # Pass database ID, not gid
        from .tasks import download_missing_albums_for_artist

        download_missing_albums_for_artist.delay(artist.id, **extra_args)


def enqueue_batch_artist_operations(
    artists: QuerySet[Artist],
    operations: Optional[List[str]] = None,
    extra_args: Optional[dict] = None,
) -> Dict[str, int]:
    """
    Enqueue multiple operations for multiple artists in batch.

    Args:
        artists: QuerySet of artists to process
        operations: List of operations to perform (e.g., ['fetch', 'download'])
        extra_args: Additional arguments to pass to operations

    Returns:
        Dict with operation counts
    """
    if extra_args is None:
        extra_args = {}

    if operations is None:
        operations = ["fetch", "download"]

    # Track already enqueued artists to avoid duplicates
    already_enqueued_artists = set()
    operation_counts: dict[str, int] = {}

    for artist in artists:
        # Use database ID for internal operations
        if artist.id in already_enqueued_artists:
            continue
        already_enqueued_artists.add(artist.id)

        # Enqueue operations based on artist status
        if "fetch" in operations:
            from .tasks import fetch_all_albums_for_artist

            # fetch_all_albums_for_artist doesn't accept extra parameters
            fetch_all_albums_for_artist.delay(artist.id)
            operation_counts["fetch"] = operation_counts.get("fetch", 0) + 1

        if "download" in operations and artist.tracking_tier >= TrackingTier.TRACKED:
            from .tasks import download_missing_albums_for_artist

            # Only download task accepts the delay parameter
            download_missing_albums_for_artist.delay(artist.id, **extra_args)
            operation_counts["download"] = operation_counts.get("download", 0) + 1

    return operation_counts


def enqueue_priority_artist_operations(
    artists: QuerySet[Artist], priority: int = 5, max_concurrent: int = 10
) -> Dict[str, int]:
    """
    Enqueue high-priority operations for artists with rate limiting.

    Args:
        artists: QuerySet of artists to process
        priority: Celery task priority (lower = higher priority)
        max_concurrent: Maximum concurrent operations

    Returns:
        Dict with operation counts
    """
    extra_args = {"priority": priority}

    # Limit concurrent operations
    limited_artists = artists[:max_concurrent]

    return enqueue_batch_artist_operations(
        limited_artists, operations=["fetch", "download"], extra_args=extra_args
    )


def enqueue_artist_sync_with_download(
    artists: QuerySet[Artist], auto_download: bool = True, delay_seconds: int = 0
) -> Dict[str, int]:
    """
    Enqueue artist sync operations with optional automatic download.

    Args:
        artists: QuerySet of artists to sync
        auto_download: Whether to automatically download missing albums
        delay_seconds: Delay between operations to avoid rate limiting

    Returns:
        Dict with operation counts
    """
    extra_args = {"delay": delay_seconds}

    operations = ["fetch"]
    if auto_download:
        operations.append("download")

    return enqueue_batch_artist_operations(
        artists, operations=operations, extra_args=extra_args
    )
