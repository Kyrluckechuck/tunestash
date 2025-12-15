"""Periodic tasks for the Spotify library manager."""

import time
from typing import Any, Optional, Set

from celery_app import app as celery_app

from .. import helpers
from ..models import (
    ALBUM_GROUPS_TO_IGNORE,
    ALBUM_TYPES_TO_DOWNLOAD,
    Album,
    PlaylistStatus,
    TaskHistory,
    TrackedPlaylist,
)
from .core import logger
from .download import download_single_album

# Rate limiting: delay between Spotify API calls (in seconds)
_API_CALL_DELAY_SECONDS = 0.5


def get_albums_with_pending_tasks() -> Set[str]:
    """Get set of album spotify_gids that already have pending/running download tasks.

    This prevents queueing duplicate download tasks for the same album when
    the periodic task runs multiple times before previous downloads complete.

    Returns:
        Set of spotify_gid strings for albums with active tasks
    """
    pending_tasks = TaskHistory.objects.filter(
        entity_type="ALBUM",
        type="DOWNLOAD",
        status__in=["PENDING", "RUNNING"],
    ).values_list("entity_id", flat=True)

    return set(pending_tasks)


@celery_app.task(
    bind=True, name="library_manager.tasks.sync_tracked_playlists"
)  # Scheduled via Celery Beat
def sync_tracked_playlists(self: Any, task_id: Optional[str] = None) -> None:
    # Check if we're rate-limited before doing any work
    # This prevents the costly loop of queueing tasks that immediately fail
    from ..models import SpotifyRateLimitState

    rate_status = SpotifyRateLimitState.get_status()
    if rate_status["is_rate_limited"]:
        seconds_remaining = rate_status.get("seconds_until_clear", 0) or 0
        logger.info(
            f"Skipping playlist sync - Spotify API rate limited for {seconds_remaining}s"
        )
        return

    # Only sync playlists that have an active status
    # Skip playlists with spotify_api_restricted, not_found, or disabled_by_user status
    # to avoid hitting rate limits from repeated failed API calls
    # Note: status=ACTIVE is equivalent to enabled=True (enabled is a computed property)
    all_enabled_playlists = TrackedPlaylist.objects.filter(
        status=PlaylistStatus.ACTIVE,
    ).order_by("last_synced_at", "id")

    # Pre-filter playlists using snapshot_id to avoid queueing unchanged playlists
    # This reduces Celery task overhead and API calls
    playlists_to_sync = _filter_changed_playlists(list(all_enabled_playlists))

    if playlists_to_sync:
        logger.info(
            f"Queueing {len(playlists_to_sync)} playlists for sync "
            f"(skipped {len(all_enabled_playlists) - len(playlists_to_sync)} unchanged)"
        )
        helpers.enqueue_playlists(playlists_to_sync, priority=None)
    else:
        logger.info("All playlists unchanged, nothing to sync")


def _filter_changed_playlists(
    playlists: list[TrackedPlaylist],
) -> list[TrackedPlaylist]:
    """Filter playlists to only those that have changed since last sync.

    Uses Spotify's snapshot_id to efficiently detect changes without fetching
    full playlist data. Playlists without a stored snapshot_id are always included.

    Args:
        playlists: List of playlists to check

    Returns:
        List of playlists that need syncing (changed or never synced)
    """
    from .core import spotdl_wrapper

    if not playlists:
        return []

    # Separate playlists that need snapshot_id check vs. those that must sync
    playlists_to_check = []
    playlists_to_sync = []

    for playlist in playlists:
        # Always sync if no snapshot_id or never synced
        if not playlist.snapshot_id or not playlist.last_synced_at:
            playlists_to_sync.append(playlist)
        else:
            playlists_to_check.append(playlist)

    if not playlists_to_check:
        return playlists_to_sync

    # Check snapshot_ids for playlists that have been synced before
    try:
        for playlist in playlists_to_check:
            # Extract playlist ID from URL
            playlist_id = None
            if "spotify:playlist:" in playlist.url:
                playlist_id = playlist.url.split("spotify:playlist:", 1)[1]
            elif "/playlist/" in playlist.url:
                playlist_id = playlist.url.split("/playlist/", 1)[1].split("?")[0]

            if not playlist_id:
                # Can't extract ID, include for safety
                playlists_to_sync.append(playlist)
                continue

            # Get current snapshot_id from Spotify
            current_snapshot = spotdl_wrapper.downloader.get_playlist_snapshot_id(
                playlist_id
            )

            # Rate limiting: delay between API calls to avoid rate limits
            time.sleep(_API_CALL_DELAY_SECONDS)

            if current_snapshot is None:
                # API call failed, include for safety
                playlists_to_sync.append(playlist)
            elif current_snapshot != playlist.snapshot_id:
                # Playlist has changed
                logger.info(f"Playlist '{playlist.name}' changed, queueing for sync")
                playlists_to_sync.append(playlist)
            else:
                # Playlist unchanged, skip
                logger.debug(f"Playlist '{playlist.name}' unchanged, skipping")

    except Exception as e:
        logger.warning(f"Error checking playlist snapshots: {e}, syncing all")
        # On error, sync all playlists that we were checking
        playlists_to_sync.extend(playlists_to_check)

    return playlists_to_sync


@celery_app.task(
    bind=True, name="library_manager.tasks.queue_missing_albums_for_tracked_artists"
)  # Scheduled via Celery Beat - Every hour
def queue_missing_albums_for_tracked_artists(self: Any) -> None:
    """
    Periodically find tracked artists with missing music and queue downloads.

    Finds up to 50 albums that are marked as wanted but not yet downloaded
    from tracked artists, and queues them for download. Runs hourly.

    Skips albums that already have pending/running download tasks to prevent
    duplicate task queuing.
    """
    try:
        logger.info("Starting periodic queue of missing albums for tracked artists")

        # Get albums that already have pending/running tasks to avoid duplicates
        albums_with_pending_tasks = get_albums_with_pending_tasks()
        if albums_with_pending_tasks:
            logger.info(
                f"Found {len(albums_with_pending_tasks)} albums with pending/running tasks, will skip"
            )

        # Find all missing albums for tracked artists
        missing_albums = (
            Album.objects.filter(
                artist__tracked=True,
                downloaded=False,
                wanted=True,
                album_type__in=ALBUM_TYPES_TO_DOWNLOAD,
            )
            .exclude(album_group__in=ALBUM_GROUPS_TO_IGNORE)
            .order_by("id")[:50]
        )

        if not missing_albums.exists():
            logger.info(
                "No missing albums found for tracked artists to queue for download"
            )
            return

        queued_count = 0
        skipped_count = 0
        for album in missing_albums.iterator():
            # Skip if album already has a pending/running task
            if album.spotify_gid in albums_with_pending_tasks:
                skipped_count += 1
                continue

            try:
                download_single_album.delay(album.id)
                queued_count += 1
            except Exception as e:
                logger.warning(f"Failed to queue album {album.name} ({album.id}): {e}")

        if skipped_count:
            logger.info(
                "Queued %d missing albums from tracked artists for download "
                "(skipped %d with pending tasks)",
                queued_count,
                skipped_count,
            )
        else:
            logger.info(
                "Queued %d missing albums from tracked artists for download",
                queued_count,
            )

    except Exception as e:
        logger.error(
            f"Error in queue_missing_albums_for_tracked_artists: {e}", exc_info=True
        )
