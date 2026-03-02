"""Periodic tasks for the Spotify library manager."""

import time
import unicodedata
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
from .core import logger, spotdl_wrapper
from .download import download_single_album

# Rate limiting: delay between Spotify API calls (in seconds)
_API_CALL_DELAY_SECONDS = 1.0

# Max albums to backfill metadata for per run (to avoid API quota issues)
_MAX_METADATA_BACKFILL_PER_RUN = 20

# Deezer-based sync constants
_DEEZER_ARTIST_CHECK_BATCH_SIZE = 50
_DEEZER_ALBUMS_TO_CHECK = 20
_MAX_PENDING_ARTIST_SYNCS = 100


def _normalize_name(name: str) -> str:
    """Strip accents and lowercase for fuzzy name comparison."""
    nfkd = unicodedata.normalize("NFKD", name)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower()


def backfill_album_metadata(limit: int = _MAX_METADATA_BACKFILL_PER_RUN) -> int:
    """
    Backfill metadata for albums with album_type=None.

    These are typically albums created from playlist syncs that only have
    basic info (GID, name) but no type/group metadata from Spotify.

    Returns the number of albums updated.
    """
    from ..models import SpotifyRateLimitState

    # Find albums missing metadata from tracked artists
    albums_needing_metadata = Album.objects.filter(
        artist__tracked=True,
        downloaded=False,
        wanted=True,
        album_type__isnull=True,
    ).order_by("id")[:limit]

    if not albums_needing_metadata.exists():
        return 0

    updated_count = 0
    for album in albums_needing_metadata:
        try:
            # Rate limiting: check if we need to wait
            delay = SpotifyRateLimitState.get_delay_seconds()
            if delay > 30:
                # Don't wait too long during backfill, just stop
                logger.info(
                    f"Stopping metadata backfill due to rate limit delay ({delay:.0f}s)"
                )
                break
            if delay > 0:
                time.sleep(delay)

            # Fetch album details from Spotify
            album_data = spotdl_wrapper.downloader.get_album(album.spotify_gid)
            SpotifyRateLimitState.record_call()

            if album_data:
                # Update album metadata
                album.album_type = album_data.get("album_type")
                album.album_group = album_data.get("album_group")
                album.save(update_fields=["album_type", "album_group"])
                updated_count += 1
                logger.debug(
                    f"Backfilled metadata for '{album.name}': "
                    f"type={album.album_type}, group={album.album_group}"
                )
        except Exception as e:
            logger.warning(
                f"Failed to backfill metadata for album {album.spotify_gid}: {e}"
            )

    if updated_count > 0:
        logger.info(f"Backfilled metadata for {updated_count} album(s)")

    return updated_count


def get_albums_with_pending_tasks() -> Set[str]:
    """Get set of album entity_ids (DB IDs) that have pending/running download tasks.

    This prevents queueing duplicate download tasks for the same album when
    the periodic task runs multiple times before previous downloads complete.

    Returns:
        Set of entity_id strings for albums with active tasks
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
    duplicate task queuing. Works for both Spotify and Deezer-only albums.
    """
    max_albums_per_run = 50

    try:
        logger.info("Starting periodic queue of missing albums for tracked artists")

        # Get albums that already have pending/running tasks (uses DB IDs)
        albums_with_pending_tasks = get_albums_with_pending_tasks()
        if albums_with_pending_tasks:
            logger.info(
                f"Found {len(albums_with_pending_tasks)} albums with pending/running tasks, will skip"
            )

        missing_albums = (
            Album.objects.filter(
                artist__tracked=True,
                downloaded=False,
                wanted=True,
                album_type__in=ALBUM_TYPES_TO_DOWNLOAD,
            )
            .exclude(album_group__in=ALBUM_GROUPS_TO_IGNORE)
            .order_by("id")[:max_albums_per_run]
        )

        queued_count = 0
        skipped_count = 0
        for album in missing_albums.iterator():
            # Compare using album DB ID (entity_id is now str(album.id))
            if str(album.id) in albums_with_pending_tasks:
                skipped_count += 1
                continue

            try:
                download_single_album.delay(album.id)
                queued_count += 1
            except Exception as e:
                logger.warning(f"Failed to queue album {album.name} ({album.id}): {e}")

        if queued_count > 0:
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

        # Use remaining capacity to backfill metadata for albums with type=None
        remaining_capacity = max_albums_per_run - queued_count
        if remaining_capacity > 0:
            backfilled = backfill_album_metadata(limit=remaining_capacity)
            if backfilled == 0 and queued_count == 0:
                logger.info(
                    "No missing albums found for tracked artists to queue for download"
                )

    except Exception as e:
        logger.error(
            f"Error in queue_missing_albums_for_tracked_artists: {e}", exc_info=True
        )


@celery_app.task(
    bind=True, name="library_manager.tasks.sync_tracked_artists_metadata"
)  # Scheduled via Celery Beat - Every hour at :30
def sync_tracked_artists_metadata(
    self: Any, batch_size: int = _DEEZER_ARTIST_CHECK_BATCH_SIZE
) -> None:
    """
    Periodically sync metadata for tracked artists to discover new releases.

    Uses Deezer API to check for new albums. For each tracked artist:
    1. If no deezer_id: search Deezer by name and link if found
    2. Fetch recent albums from Deezer
    3. Compare against DB albums (by deezer_id or name match)
    4. Queue full Deezer sync for artists with new albums

    Deezer's generous rate limits (~10 req/s) allow checking many artists per run.
    """
    from django.db.models import Q

    from src.providers.deezer import DeezerMetadataProvider

    from .deezer import fetch_artist_albums_from_deezer

    try:
        # Backpressure: check pending artist syncs
        pending_syncs = TaskHistory.objects.filter(
            task_id__startswith="library_manager.tasks.fetch_artist_albums_from_deezer",
            status__in=["PENDING", "RUNNING"],
        ).count()

        if pending_syncs >= _MAX_PENDING_ARTIST_SYNCS:
            logger.info(
                f"Skipping artist metadata sync - {pending_syncs} syncs already pending "
                f"(cap: {_MAX_PENDING_ARTIST_SYNCS})"
            )
            return

        artists_to_check = Artist.objects.filter(tracked=True).order_by(
            "last_synced_at", "id"
        )[:batch_size]

        if not artists_to_check.exists():
            logger.info("No tracked artists found to sync")
            return

        total_count = Artist.objects.filter(tracked=True).count()
        logger.info(
            f"Starting Deezer-based artist metadata sync: "
            f"checking {len(artists_to_check)} of {total_count} tracked artists"
        )

        provider = DeezerMetadataProvider()
        queued_count = 0
        skipped_unchanged = 0
        skipped_pending = 0
        linked_count = 0
        checked_count = 0

        for artist in artists_to_check:
            # Generate deterministic task ID for deduplication
            task_id = generate_task_id(
                "library_manager.tasks.fetch_artist_albums_from_deezer", artist.id
            )

            is_pending, reason = is_task_pending_or_running(task_id)
            if is_pending:
                logger.debug(
                    f"[DEDUP] Skipping artist {artist.name}: "
                    f"task already queued ({reason})"
                )
                skipped_pending += 1
                continue

            # Link Deezer ID if missing (one-time per artist)
            if not artist.deezer_id:
                try:
                    results = provider.search_artists(artist.name, limit=3)
                    match = next(
                        (
                            r
                            for r in results
                            if _normalize_name(r.name) == _normalize_name(artist.name)
                            and r.deezer_id
                        ),
                        None,
                    )
                    if match and match.deezer_id:
                        artist.deezer_id = match.deezer_id
                        artist.save(update_fields=["deezer_id"])
                        linked_count += 1
                        logger.info(
                            f"Linked artist '{artist.name}' to Deezer ID {match.deezer_id}"
                        )
                    else:
                        artist.last_synced_at = timezone.now()
                        artist.save(update_fields=["last_synced_at"])
                        skipped_unchanged += 1
                        continue
                except Exception as e:
                    logger.warning(
                        f"Failed to search Deezer for artist '{artist.name}': {e}"
                    )
                    artist.last_synced_at = timezone.now()
                    artist.save(update_fields=["last_synced_at"])
                    skipped_unchanged += 1
                    continue

            checked_count += 1

            try:
                recent_albums = provider.get_artist_albums(
                    artist.deezer_id, limit=_DEEZER_ALBUMS_TO_CHECK
                )
            except Exception as e:
                logger.debug(f"Failed to fetch Deezer albums for {artist.name}: {e}")
                continue

            if not recent_albums:
                artist.last_synced_at = timezone.now()
                artist.save(update_fields=["last_synced_at"])
                skipped_unchanged += 1
                continue

            # Check if any fetched albums are missing from our database
            deezer_album_ids = [
                a.deezer_id for a in recent_albums if a.deezer_id is not None
            ]
            album_names = [a.name for a in recent_albums]

            known_albums = Album.objects.filter(
                Q(artist=artist, deezer_id__in=deezer_album_ids)
                | Q(artist=artist, name__in=album_names)
            )
            known_deezer_ids = set(
                known_albums.filter(deezer_id__isnull=False).values_list(
                    "deezer_id", flat=True
                )
            )
            known_names = set(known_albums.values_list("name", flat=True))

            new_album_count = 0
            for album_data in recent_albums:
                is_known = (
                    album_data.deezer_id and album_data.deezer_id in known_deezer_ids
                ) or album_data.name in known_names
                if not is_known:
                    new_album_count += 1

            if new_album_count > 0:
                logger.info(
                    f"Artist '{artist.name}' has {new_album_count} new album(s), "
                    f"queueing Deezer sync"
                )
                try:
                    fetch_artist_albums_from_deezer.apply_async(
                        args=[artist.id], task_id=task_id
                    )
                    queued_count += 1
                except Exception as e:
                    logger.warning(
                        f"Failed to queue Deezer sync for artist {artist.name}: {e}"
                    )
            else:
                artist.last_synced_at = timezone.now()
                artist.save(update_fields=["last_synced_at"])
                skipped_unchanged += 1

        logger.info(
            f"Artist metadata sync complete: "
            f"checked {checked_count} artists, "
            f"queued {queued_count} for Deezer sync, "
            f"linked {linked_count} new Deezer IDs, "
            f"skipped {skipped_unchanged} unchanged, "
            f"skipped {skipped_pending} with pending tasks"
        )

    except Exception as e:
        logger.error(f"Error in sync_tracked_artists_metadata: {e}", exc_info=True)
