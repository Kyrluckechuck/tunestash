"""Periodic tasks for the Spotify library manager."""

import time
from typing import Any, Optional, Set

from django.utils import timezone

from celery_app import app as celery_app

from .. import helpers
from ..helpers import generate_task_id, is_task_pending_or_running
from ..models import (
    ALBUM_GROUPS_TO_IGNORE,
    ALBUM_TYPES_TO_DOWNLOAD,
    Album,
    Artist,
    PlaylistStatus,
    TaskHistory,
    TrackedPlaylist,
)
from .core import logger
from .download import download_single_album

# Rate limiting: delay between Spotify API calls (in seconds)
_API_CALL_DELAY_SECONDS = 1.0


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
    from ..models import SpotifyRateLimitState

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

            # Rate limiting: check if we need to wait before making API call
            delay = SpotifyRateLimitState.get_delay_seconds()
            if delay > 0:
                time.sleep(delay)

            # Get current snapshot_id from Spotify
            current_snapshot = spotdl_wrapper.downloader.get_playlist_snapshot_id(
                playlist_id
            )

            # Record this API call in the rate limit tracker
            SpotifyRateLimitState.record_call()

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
    # Check if we're rate-limited before doing any work
    # This prevents queueing tasks that will immediately fail
    from ..models import SpotifyRateLimitState

    rate_status = SpotifyRateLimitState.get_status()
    if rate_status["is_rate_limited"]:
        seconds_remaining = rate_status.get("seconds_until_clear", 0) or 0
        logger.info(
            f"Skipping album queue - Spotify API rate limited for {seconds_remaining}s"
        )
        return

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


# Batch size for lightweight artist change detection
# Each check is 1 API call with ~1s delay, so 50 artists ≈ 50 calls in ~1 minute
# This uses ~50% of the sustained rate limit (100/5min), leaving headroom for:
# - User activity (manual syncs, downloads)
# - Other periodic tasks (playlist syncs, album downloads)
# - Full syncs triggered when changes are detected (~2-10 extra calls)
_ARTIST_CHECK_BATCH_SIZE = 50

# Number of recent albums to fetch per artist for change detection
# Fetching 20 costs the same as fetching 1 (1 API call), but is more robust
_ALBUMS_TO_CHECK = 20

# Maximum number of pending/running artist sync tasks before we stop queueing more
# This provides backpressure during initial population or high-load periods,
# preventing unbounded queue growth when we can't process tasks fast enough
_MAX_PENDING_ARTIST_SYNCS = 100


@celery_app.task(
    bind=True, name="library_manager.tasks.sync_tracked_artists_metadata"
)  # Scheduled via Celery Beat - Every hour at :30
def sync_tracked_artists_metadata(
    self: Any, batch_size: int = _ARTIST_CHECK_BATCH_SIZE
) -> None:
    """
    Periodically sync metadata for tracked artists to discover new releases.

    Uses a two-phase approach to minimize API usage:
    1. Lightweight check: Fetch recent album IDs (1 API call per artist, 20 albums)
    2. Compare against DB: Check if any fetched albums are missing
    3. Full sync: Only for artists with new/missing albums

    This dramatically reduces API calls since most artists (~95-99%) won't have
    new releases on any given day. Instead of 2+ API calls per artist for full sync,
    we use 1 call for the check and only do full syncs for the ~1-5% that changed.

    With default batch_size=50 and running every hour:
    - 50 lightweight checks = 50 API calls (~50% of sustained rate limit)
    - Typically ~1-3 artists need full sync = ~2-6 additional API calls
    - Leaves headroom for user activity and other periodic tasks
    - Full rotation of 1000 artists: ~20 hours (vs ~3.5 days with old approach)

    All API calls are tracked via SpotifyRateLimitState to coordinate with other
    tasks and prevent rate limit violations.
    """
    from ..models import SpotifyRateLimitState
    from .artist import fetch_all_albums_for_artist
    from .core import spotdl_wrapper

    # Check if we're rate-limited before doing any work
    rate_status = SpotifyRateLimitState.get_status()
    if rate_status["is_rate_limited"]:
        seconds_remaining = rate_status.get("seconds_until_clear", 0) or 0
        logger.info(
            f"Skipping artist metadata sync - Spotify API rate limited for {seconds_remaining}s"
        )
        return

    # Backpressure: check if there are too many pending artist syncs already
    # This prevents unbounded queue growth during initial population
    pending_syncs = TaskHistory.objects.filter(
        task_name="fetch_all_albums_for_artist",
        status__in=["PENDING", "RUNNING"],
    ).count()

    if pending_syncs >= _MAX_PENDING_ARTIST_SYNCS:
        logger.info(
            f"Skipping artist metadata sync - {pending_syncs} syncs already pending "
            f"(cap: {_MAX_PENDING_ARTIST_SYNCS})"
        )
        return

    try:
        # Get tracked artists ordered by last_synced_at (oldest/never synced first)
        artists_to_check = Artist.objects.filter(tracked=True).order_by(
            "last_synced_at", "id"
        )[:batch_size]

        if not artists_to_check.exists():
            logger.info("No tracked artists found to sync")
            return

        total_count = Artist.objects.filter(tracked=True).count()
        logger.info(
            f"Starting periodic artist metadata sync: checking {len(artists_to_check)} of {total_count} tracked artists"
        )

        queued_count = 0
        skipped_unchanged = 0
        skipped_pending = 0

        for artist in artists_to_check:
            # Generate deterministic task ID for deduplication
            task_id = generate_task_id(
                "library_manager.tasks.fetch_all_albums_for_artist", artist.id
            )

            # Skip if task is already queued or running
            is_pending, reason = is_task_pending_or_running(task_id)
            if is_pending:
                logger.debug(
                    f"[DEDUP] Skipping artist {artist.name}: task already queued ({reason})"
                )
                skipped_pending += 1
                continue

            # Rate limiting: check if we need to wait before making API call
            delay = SpotifyRateLimitState.get_delay_seconds()
            if delay > 0:
                logger.debug(f"Rate limit delay: sleeping {delay:.1f}s before API call")
                time.sleep(delay)

            # Lightweight check: fetch recent album IDs from Spotify (1 API call)
            recent_album_ids = spotdl_wrapper.downloader.get_artist_recent_album_ids(
                artist.gid, limit=_ALBUMS_TO_CHECK
            )

            # Record this API call in the rate limit tracker
            SpotifyRateLimitState.record_call()

            if recent_album_ids is None:
                # API call failed, skip this artist for now
                logger.debug(
                    f"Failed to check recent albums for {artist.name}, skipping"
                )
                continue

            if not recent_album_ids:
                # Artist has no albums, just update last_synced_at
                artist.last_synced_at = timezone.now()
                artist.save(update_fields=["last_synced_at"])
                skipped_unchanged += 1
                continue

            # Check if any of the fetched albums are missing from our database
            known_album_ids = set(
                Album.objects.filter(
                    artist=artist, spotify_gid__in=recent_album_ids
                ).values_list("spotify_gid", flat=True)
            )
            missing_albums = set(recent_album_ids) - known_album_ids

            if missing_albums:
                # Artist has new releases we don't know about
                logger.info(
                    f"Artist '{artist.name}' has {len(missing_albums)} new album(s), "
                    f"queueing full sync"
                )
                try:
                    fetch_all_albums_for_artist.apply_async(
                        args=[artist.id], task_id=task_id
                    )
                    queued_count += 1
                except Exception as e:
                    logger.warning(
                        f"Failed to queue sync for artist {artist.name}: {e}"
                    )
            else:
                # All fetched albums are known, no changes
                artist.last_synced_at = timezone.now()
                artist.save(update_fields=["last_synced_at"])
                skipped_unchanged += 1

        logger.info(
            f"Artist metadata sync complete: "
            f"queued {queued_count} for full sync, "
            f"skipped {skipped_unchanged} unchanged, "
            f"skipped {skipped_pending} with pending tasks"
        )

    except Exception as e:
        logger.error(f"Error in sync_tracked_artists_metadata: {e}", exc_info=True)


# Number of pages to fetch from New Releases endpoint (50 albums per page)
# Spotify limits new releases to 100 total, so 2 pages covers everything
_NEW_RELEASES_PAGES = 2


@celery_app.task(
    bind=True, name="library_manager.tasks.scan_new_releases_for_tracked_artists"
)  # Scheduled via Celery Beat - Every hour at :00
def scan_new_releases_for_tracked_artists(
    self: Any, pages: int = _NEW_RELEASES_PAGES
) -> None:
    """
    Scan Spotify's New Releases for albums from tracked artists.

    This provides fast detection of new music from popular/featured artists by
    checking Spotify's curated "New Releases" page instead of waiting for the
    artist to come up in the rotation.

    Complements sync_tracked_artists_metadata:
    - New Releases scan: Fast detection for featured releases (major artists)
    - Artist rotation: Complete coverage for all releases (including indie)

    Spotify limits new releases to 100 albums total. With default pages=2:
    - 2 API calls per hour (covers all 100 new releases)
    - Immediate detection of tracked artists in featured releases
    - Triggers artist sync only when new album is found
    """
    from ..models import SpotifyRateLimitState
    from .artist import fetch_all_albums_for_artist
    from .core import spotdl_wrapper

    # Check if we're rate-limited before doing any work
    rate_status = SpotifyRateLimitState.get_status()
    if rate_status["is_rate_limited"]:
        seconds_remaining = rate_status.get("seconds_until_clear", 0) or 0
        logger.info(
            f"Skipping new releases scan - Spotify API rate limited for {seconds_remaining}s"
        )
        return

    try:
        # Get all tracked artist GIDs for quick lookup
        tracked_artist_gids = set(
            Artist.objects.filter(tracked=True).values_list("gid", flat=True)
        )

        if not tracked_artist_gids:
            logger.info("No tracked artists found, skipping new releases scan")
            return

        logger.info(
            f"Scanning new releases for {len(tracked_artist_gids)} tracked artists "
            f"({pages} pages = {pages * 50} albums)"
        )

        artists_to_sync: set[str] = set()  # Artist GIDs that need syncing
        albums_checked = 0

        for page in range(pages):
            # Rate limiting: check if we need to wait before making API call
            delay = SpotifyRateLimitState.get_delay_seconds()
            if delay > 0:
                logger.debug(f"Rate limit delay: sleeping {delay:.1f}s before API call")
                time.sleep(delay)

            # Fetch new releases page
            new_releases = spotdl_wrapper.downloader.get_new_releases(
                limit=50, offset=page * 50
            )

            # Record this API call in the rate limit tracker
            SpotifyRateLimitState.record_call()

            if new_releases is None:
                logger.warning(f"Failed to fetch new releases page {page}, stopping")
                break

            if not new_releases:
                logger.debug(f"No more new releases at page {page}")
                break

            albums_checked += len(new_releases)

            # Check each release for tracked artists
            for release in new_releases:
                album_id = release.get("id")
                if not album_id:
                    continue

                # Get tracked artist GIDs from this release
                release_artist_gids = [
                    a.get("id")
                    for a in release.get("artists", [])
                    if a.get("id") in tracked_artist_gids
                ]
                if not release_artist_gids:
                    continue

                # Check if we already have this album
                if Album.objects.filter(spotify_gid=album_id).exists():
                    continue

                # New release from tracked artist(s)!
                artist_names = [
                    a.get("name")
                    for a in release.get("artists", [])
                    if a.get("id") in release_artist_gids
                ]
                logger.info(
                    f"New release found: '{release.get('name')}' "
                    f"by {', '.join(artist_names)} (tracked)"
                )
                artists_to_sync.update(release_artist_gids)

        # Queue syncs for artists with new releases
        queued_count = 0
        for artist_gid in artists_to_sync:
            try:
                artist = Artist.objects.get(gid=artist_gid)
                task_id = generate_task_id(
                    "library_manager.tasks.fetch_all_albums_for_artist", artist.id
                )

                # Skip if task is already queued or running
                is_pending, reason = is_task_pending_or_running(task_id)
                if is_pending:
                    logger.debug(
                        f"[DEDUP] Skipping artist {artist.name}: task already queued ({reason})"
                    )
                    continue

                fetch_all_albums_for_artist.apply_async(
                    args=[artist.id], task_id=task_id
                )
                queued_count += 1
            except Artist.DoesNotExist:
                continue
            except Exception as e:
                logger.warning(f"Failed to queue sync for artist {artist_gid}: {e}")

        logger.info(
            f"New releases scan complete: checked {albums_checked} albums, "
            f"queued {queued_count} artist syncs"
        )

    except Exception as e:
        logger.error(
            f"Error in scan_new_releases_for_tracked_artists: {e}", exc_info=True
        )
