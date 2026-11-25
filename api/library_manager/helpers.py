import hashlib
import logging
from datetime import timedelta
from typing import Any, Dict, List, Optional, Sequence

from django.db import IntegrityError, transaction
from django.db.models import QuerySet
from django.utils import timezone

from .models import Artist, TaskHistory, TrackedPlaylist, TrackingTier

logger = logging.getLogger(__name__)

# A PENDING claim that never started within this window is assumed lost
# (purged queue, dropped message) and may be reclaimed.
STALE_CLAIM_AGE = timedelta(hours=6)

# Celery Task Deduplication Utilities


def generate_task_id(task_name: str, *args: object, **kwargs: object) -> str:
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

    # Check TaskHistory (app tracking): enqueue claims (PENDING) and running tasks
    try:
        task_history = TaskHistory.objects.get(task_id=task_id)
        if task_history.status in task_history_active_states:
            claim_expired = (
                task_history.status == "PENDING"
                and task_history.started_at < timezone.now() - STALE_CLAIM_AGE
            )
            if not claim_expired:
                return True, f"TaskHistory.status={task_history.status}"
            logger.info(
                f"[DEDUP] Reclaiming stale PENDING claim for {task_id} "
                f"(queued {task_history.started_at})"
            )
        # Terminal state - delete so we can re-queue with same task_id
        logger.info(
            f"[DEDUP] Clearing stale TaskHistory for {task_id} "
            f"(status={task_history.status})"
        )
        task_history.delete()
    except TaskHistory.DoesNotExist:
        pass

    return False, ""


def enqueue_deduped(
    task: Any,
    *,
    task_id: str,
    args: Optional[Sequence[Any]] = None,
    kwargs: Optional[Dict[str, Any]] = None,
    priority: Optional[int] = None,
    queue: Optional[str] = None,
    countdown: Optional[int] = None,
    task_type: str = "UNKNOWN",
    entity_type: str = "UNKNOWN",
    entity_id: str = "unknown",
    claim_nonce: Optional[str] = None,
    nonce_key: str = "nonce",
    initial_metadata: Optional[Dict[str, Any]] = None,
) -> bool:
    """Publish ``task`` unless an active task with ``task_id`` already exists.

    The dedup decision is a single atomic INSERT of a PENDING TaskHistory row
    (``task_id`` is unique), so two concurrent callers cannot both publish.
    The task body adopts that row via ``create_task_history`` when it starts.
    The claim is released if publishing fails.

    ``queue`` and ``countdown`` are forwarded to ``apply_async`` so callers
    that use a dedicated queue or a delayed start keep that routing.

    ``claim_nonce`` / ``nonce_key`` are optional and backwards compatible.
    When a nonce is supplied, the publish-failure cleanup also requires the
    claim to still carry that nonce in its ``log_messages`` metadata, so a
    newer generation that reused the same row cannot be deleted by a stale
    publisher. Pass ``nonce_key="export_sync_nonce"`` for QueueTip claims.

    ``initial_metadata`` is written in the same INSERT as the PENDING claim,
    so publishers cannot race to overwrite another generation's nonce.

    Returns True if the task was published, False if an active claim exists.
    """
    is_pending, reason = is_task_pending_or_running(task_id)
    if is_pending:
        logger.info(f"[DEDUP] Skipping {task_id}: {reason}")
        return False

    try:
        with transaction.atomic():
            claim = TaskHistory.objects.create(
                task_id=task_id,
                type=task_type,
                entity_type=entity_type,
                entity_id=str(entity_id),
                status="PENDING",
                log_messages=[initial_metadata] if initial_metadata else [],
            )
    except IntegrityError:
        logger.info(f"[DEDUP] Skipping {task_id}: claimed concurrently")
        return False

    publish_kwargs: Dict[str, Any] = {"args": list(args or []), "task_id": task_id}
    if kwargs:
        publish_kwargs["kwargs"] = kwargs
    if priority is not None:
        publish_kwargs["priority"] = priority
    if queue is not None:
        publish_kwargs["queue"] = queue
    if countdown is not None:
        publish_kwargs["countdown"] = countdown
    try:
        task.apply_async(**publish_kwargs)
    except Exception:
        cleanup = TaskHistory.objects.filter(pk=claim.pk, status="PENDING")
        if claim_nonce is not None:
            # The nonce lives in the JSON log metadata written by the caller
            # at publish time; only release the exact attempt we created.
            cleanup = cleanup.filter(log_messages__contains=[{nonce_key: claim_nonce}])
        cleanup.delete()
        raise
    return True


def enqueue_fetch_all_albums_for_artist(
    artist_id: int, priority: Optional[int] = None, task: Any = None
) -> bool:
    """Queue an album fetch for an artist; one active fetch per artist."""
    if task is None:
        from .tasks import fetch_all_albums_for_artist as task
    return enqueue_deduped(
        task,
        task_id=generate_task_id(
            "library_manager.tasks.fetch_all_albums_for_artist", artist_id
        ),
        args=[artist_id],
        priority=priority,
        task_type="FETCH",
        entity_type="ARTIST",
        entity_id=str(artist_id),
    )


def enqueue_download_missing_albums_for_artist(
    artist_id: int,
    delay: int = 0,
    priority: Optional[int] = None,
    task: Any = None,
) -> bool:
    """Queue a missing-album download for an artist.

    The task id ignores ``delay`` so every caller shares one id and dedupes
    against the others.
    """
    if task is None:
        from .tasks import download_missing_albums_for_artist as task
    return enqueue_deduped(
        task,
        task_id=generate_task_id(
            "library_manager.tasks.download_missing_albums_for_artist", artist_id
        ),
        args=[artist_id],
        kwargs={"delay": delay},
        priority=priority,
        task_type="DOWNLOAD",
        entity_type="ARTIST",
        entity_id=str(artist_id),
    )


def _dedup_task_id(task_name: str, entity_id: object) -> str:
    """Build the shared task id used by a task and all of its deduped callers."""
    return generate_task_id(task_name, entity_id)


def enqueue_download_album_by_spotify_id(
    spotify_album_id: str, priority: Optional[int] = None
) -> bool:
    from .tasks import download_album_by_spotify_id

    return enqueue_deduped(
        download_album_by_spotify_id,
        task_id=_dedup_task_id(
            "library_manager.tasks.download_album_by_spotify_id", spotify_album_id
        ),
        args=[spotify_album_id],
        priority=priority,
        task_type="DOWNLOAD",
        entity_type="ALBUM",
        entity_id=str(spotify_album_id),
    )


def enqueue_download_single_album(
    album_id: int, priority: Optional[int] = None
) -> bool:
    from .tasks import download_single_album

    return enqueue_deduped(
        download_single_album,
        task_id=_dedup_task_id("library_manager.tasks.download_single_album", album_id),
        args=[album_id],
        priority=priority,
        task_type="DOWNLOAD",
        entity_type="ALBUM",
        entity_id=str(album_id),
    )


def enqueue_download_album_by_deezer_id(
    deezer_album_id: int, priority: Optional[int] = None
) -> bool:
    from .tasks import download_album_by_deezer_id

    return enqueue_deduped(
        download_album_by_deezer_id,
        task_id=_dedup_task_id(
            "library_manager.tasks.download_album_by_deezer_id", deezer_album_id
        ),
        args=[deezer_album_id],
        priority=priority,
        task_type="DOWNLOAD",
        entity_type="ALBUM",
        entity_id=str(deezer_album_id),
    )


def enqueue_download_deezer_track(song_id: int, priority: Optional[int] = None) -> bool:
    from .tasks import download_deezer_track

    return enqueue_deduped(
        download_deezer_track,
        task_id=_dedup_task_id("library_manager.tasks.download_deezer_track", song_id),
        args=[song_id],
        priority=priority,
        task_type="DOWNLOAD",
        entity_type="TRACK",
        entity_id=str(song_id),
    )


def enqueue_download_track_by_spotify_gid(
    track_gid: str, priority: Optional[int] = None
) -> bool:
    from .tasks import download_track_by_spotify_gid

    return enqueue_deduped(
        download_track_by_spotify_gid,
        task_id=_dedup_task_id(
            "library_manager.tasks.download_track_by_spotify_gid", track_gid
        ),
        args=[track_gid],
        priority=priority,
        task_type="DOWNLOAD",
        entity_type="TRACK",
        entity_id=str(track_gid),
    )


def enqueue_apply_metadata_update(
    update_id: int, priority: Optional[int] = None
) -> bool:
    from .tasks import apply_metadata_update

    return enqueue_deduped(
        apply_metadata_update,
        task_id=_dedup_task_id(
            "library_manager.tasks.apply_metadata_update", update_id
        ),
        args=[update_id],
        priority=priority,
        task_type="SYNC",
        entity_type="METADATA_UPDATE",
        entity_id=str(update_id),
    )


def enqueue_map_external_list_tracks(
    list_id: int, priority: Optional[int] = None
) -> bool:
    from .tasks import map_external_list_tracks

    return enqueue_deduped(
        map_external_list_tracks,
        task_id=_dedup_task_id(
            "library_manager.tasks.map_external_list_tracks", list_id
        ),
        args=[list_id],
        priority=priority,
        task_type="SYNC",
        entity_type="PLAYLIST",
        entity_id=str(list_id),
    )


def enqueue_sync_deezer_playlist(
    playlist_id: int, priority: Optional[int] = None
) -> bool:
    from .tasks import sync_deezer_playlist

    return enqueue_deduped(
        sync_deezer_playlist,
        task_id=_dedup_task_id(
            "library_manager.tasks.sync_deezer_playlist", playlist_id
        ),
        args=[playlist_id],
        priority=priority,
        task_type="SYNC",
        entity_type="PLAYLIST",
        entity_id=str(playlist_id),
    )


def update_tracked_artists_albums(
    already_enqueued_artists: List[int],
    artists_to_enqueue: List[Artist],
    priority: Optional[int] = None,
) -> None:
    # Local imports to avoid circular import during module initialization
    from .task_priorities import TaskPriority
    from .tasks import fetch_all_albums_for_artist

    # Use background priority for artist sync if not specified
    effective_priority = priority if priority is not None else TaskPriority.ARTIST_SYNC

    for artist in artists_to_enqueue:
        # Use database ID for internal operations
        if artist.id in already_enqueued_artists:
            continue

        enqueue_fetch_all_albums_for_artist(
            artist.id, priority=effective_priority, task=fetch_all_albums_for_artist
        )


def download_missing_tracked_artists(
    already_enqueued_artists: List[int],
    artists_to_enqueue: List[Artist],
    priority: Optional[int] = None,
) -> None:
    # Local imports to avoid circular import during module initialization
    from .models import SpotifyRateLimitState
    from .task_priorities import TaskPriority
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

        enqueue_download_missing_albums_for_artist(
            artist.id,
            delay=5,
            priority=effective_priority,
            task=download_missing_albums_for_artist,
        )


def download_non_enqueued_playlists(
    already_enqueued_playlists: List[str],
    playlists_to_enqueue: List[TrackedPlaylist],
    priority: Optional[int] = None,
) -> None:
    # Local imports to avoid circular import during module initialization
    from .models import PlaylistStatus, SpotifyRateLimitState
    from .task_priorities import TaskPriority
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
            if enqueue_deduped(
                sync_deezer_playlist,
                task_id=task_id,
                args=[playlist.id],
                priority=effective_priority,
                task_type="SYNC",
                entity_type="PLAYLIST",
                entity_id=str(playlist.id),
            ):
                logger.info(f"[ENQUEUE] Queued Deezer sync: {playlist.name}")
        else:
            # Spotify playlist — skip if rate limited
            if spotify_rate_limited:
                logger.info(f"[ENQUEUE] SKIP: {playlist.name} - Spotify rate limited")
                continue

            task_id = generate_task_id(
                "library_manager.tasks.download_playlist",
                playlist.url,
                tracking_tier=playlist.auto_track_tier,
            )

            if enqueue_deduped(
                download_playlist,
                task_id=task_id,
                kwargs={
                    "playlist_url": playlist.url,
                    "tracking_tier": playlist.auto_track_tier,
                },
                priority=effective_priority,
                task_type="DOWNLOAD",
                entity_type="PLAYLIST",
                entity_id=str(playlist.id),
            ):
                logger.info(f"[ENQUEUE] Queued Spotify download: {playlist.name}")


def enqueue_playlists(
    playlists_to_enqueue: List[TrackedPlaylist], priority: Optional[int] = None
) -> None:
    download_non_enqueued_playlists([], playlists_to_enqueue, priority=priority)


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
            # fetch_all_albums_for_artist doesn't accept extra parameters
            if enqueue_fetch_all_albums_for_artist(artist.id):
                operation_counts["fetch"] = operation_counts.get("fetch", 0) + 1

        if "download" in operations and artist.tracking_tier >= TrackingTier.TRACKED:
            # Only download task accepts the delay parameter
            if enqueue_download_missing_albums_for_artist(artist.id, **extra_args):
                operation_counts["download"] = operation_counts.get("download", 0) + 1

    return operation_counts


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
