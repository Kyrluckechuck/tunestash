"""Periodic tasks for the Tunestash."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, Optional, Set  # noqa: E402

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
from .core import logger, normalize_name
from .download import download_single_album

if TYPE_CHECKING:
    from src.providers.deezer import DeezerMetadataProvider

# Rate limiting: delay between Spotify API calls (in seconds)
_API_CALL_DELAY_SECONDS = 1.0

# Max albums to backfill metadata for per run (to avoid API quota issues)
_MAX_METADATA_BACKFILL_PER_RUN = 20

# Deezer-based sync constants
_DEEZER_ARTIST_CHECK_BATCH_SIZE = 50
_DEEZER_ALBUMS_TO_CHECK = 20
_MAX_PENDING_ARTIST_SYNCS = 100


def backfill_album_metadata(limit: int = _MAX_METADATA_BACKFILL_PER_RUN) -> int:
    """Backfill metadata for albums with album_type=None using Deezer API.

    Returns the number of albums updated.
    """
    from src.providers.deezer import DeezerMetadataProvider

    albums_needing_metadata = Album.objects.filter(
        artist__tracked=True,
        downloaded=False,
        wanted=True,
        album_type__isnull=True,
        deezer_id__isnull=False,
    ).order_by("id")[:limit]

    if not albums_needing_metadata.exists():
        return 0

    provider = DeezerMetadataProvider()
    updated_count = 0

    for album in albums_needing_metadata:
        try:
            album_data = provider.get_album(album.deezer_id)
            if album_data:
                update_fields: list[str] = []
                if album_data.album_type:
                    album.album_type = album_data.album_type
                    update_fields.append("album_type")
                if album_data.album_group:
                    album.album_group = album_data.album_group
                    update_fields.append("album_group")
                elif album_data.album_type:
                    album.album_group = album_data.album_type
                    update_fields.append("album_group")
                if update_fields:
                    album.save(update_fields=update_fields)
                    updated_count += 1
        except Exception as e:
            logger.warning(
                f"Failed to backfill metadata for album {album.name} "
                f"(deezer_id={album.deezer_id}): {e}"
            )

    if updated_count > 0:
        logger.info(f"Backfilled metadata for {updated_count} album(s) via Deezer")

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
    all_enabled_playlists = TrackedPlaylist.objects.filter(
        status=PlaylistStatus.ACTIVE,
    ).order_by("last_synced_at", "id")

    # Split by provider
    spotify_playlists = [p for p in all_enabled_playlists if p.provider != "deezer"]
    deezer_playlists = [p for p in all_enabled_playlists if p.provider == "deezer"]

    # --- Spotify playlists ---
    if spotify_playlists:
        from ..models import SpotifyRateLimitState

        rate_status = SpotifyRateLimitState.get_status()
        if rate_status["is_rate_limited"]:
            seconds_remaining = rate_status.get("seconds_until_clear", 0) or 0
            logger.info(
                f"Skipping Spotify playlist sync - rate limited for {seconds_remaining}s"
            )
        else:
            playlists_to_sync = _filter_changed_playlists(spotify_playlists)
            if playlists_to_sync:
                logger.info(
                    f"Queueing {len(playlists_to_sync)} Spotify playlists for sync "
                    f"(skipped {len(spotify_playlists) - len(playlists_to_sync)} unchanged)"
                )
                helpers.enqueue_playlists(playlists_to_sync, priority=None)
            else:
                logger.info("All Spotify playlists unchanged, nothing to sync")

    # --- Deezer playlists ---
    if deezer_playlists:
        deezer_to_sync = _filter_changed_deezer_playlists(deezer_playlists)
        if deezer_to_sync:
            from .playlist import sync_deezer_playlist

            logger.info(
                f"Queueing {len(deezer_to_sync)} Deezer playlists for sync "
                f"(skipped {len(deezer_playlists) - len(deezer_to_sync)} unchanged)"
            )
            for playlist in deezer_to_sync:
                sync_deezer_playlist.delay(playlist.pk)
        else:
            logger.info("All Deezer playlists unchanged, nothing to sync")

    if not spotify_playlists and not deezer_playlists:
        logger.info("No active playlists to sync")


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
    from downloader.downloader import SpotifyPlaylistClient

    if not playlists:
        return []

    client = SpotifyPlaylistClient.create()
    if not client.is_available():
        logger.info("Spotify OAuth not available, skipping playlist change detection")
        return list(playlists)

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

    from ..models import SpotifyRateLimitState

    try:
        for playlist in playlists_to_check:
            playlist_id = None
            if "spotify:playlist:" in playlist.url:
                playlist_id = playlist.url.split("spotify:playlist:", 1)[1]
            elif "/playlist/" in playlist.url:
                playlist_id = playlist.url.split("/playlist/", 1)[1].split("?")[0]

            if not playlist_id:
                playlists_to_sync.append(playlist)
                continue

            delay = SpotifyRateLimitState.get_delay_seconds()
            if delay > 0:
                time.sleep(delay)

            current_snapshot = client.get_playlist_snapshot_id(playlist_id)

            SpotifyRateLimitState.record_call()

            if current_snapshot is None:
                playlists_to_sync.append(playlist)
            elif current_snapshot != playlist.snapshot_id:
                logger.info(f"Playlist '{playlist.name}' changed, queueing for sync")
                playlists_to_sync.append(playlist)
            else:
                logger.debug(f"Playlist '{playlist.name}' unchanged, skipping")

    except Exception as e:
        logger.warning(f"Error checking playlist snapshots: {e}, syncing all")
        playlists_to_sync.extend(playlists_to_check)

    return playlists_to_sync


def _filter_changed_deezer_playlists(
    playlists: list[TrackedPlaylist],
) -> list[TrackedPlaylist]:
    """Filter Deezer playlists to only those that have changed since last sync.

    Uses Deezer's checksum (stored in snapshot_id) to detect changes.
    Playlists synced within the last hour are skipped to avoid unnecessary API calls.
    """
    from datetime import timedelta

    from src.providers.deezer import DeezerMetadataProvider

    if not playlists:
        return []

    playlists_to_sync: list[TrackedPlaylist] = []
    one_hour_ago = timezone.now() - timedelta(hours=1)
    provider = DeezerMetadataProvider()

    for playlist in playlists:
        # Always sync if no snapshot_id or never synced
        if not playlist.snapshot_id or not playlist.last_synced_at:
            playlists_to_sync.append(playlist)
            continue

        # Skip recently synced playlists
        if playlist.last_synced_at > one_hour_ago:
            logger.debug(f"Deezer playlist '{playlist.name}' synced recently, skipping")
            continue

        # Extract Deezer playlist ID from URL
        import re

        match = re.search(r"deezer\.com/(?:\w+/)?playlist/(\d+)", playlist.url)
        if not match:
            playlists_to_sync.append(playlist)
            continue

        try:
            playlist_info = provider.get_playlist(match.group(1))
            if playlist_info is None:
                playlists_to_sync.append(playlist)
            elif playlist_info.checksum != playlist.snapshot_id:
                logger.info(
                    f"Deezer playlist '{playlist.name}' changed, queueing for sync"
                )
                playlists_to_sync.append(playlist)
            else:
                logger.debug(f"Deezer playlist '{playlist.name}' unchanged, skipping")
        except Exception as e:
            logger.warning(
                f"Error checking Deezer playlist '{playlist.name}': {e}, "
                f"including for sync"
            )
            playlists_to_sync.append(playlist)

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
            .exclude(unavailable=True)
            .order_by("id")[:max_albums_per_run]
        )

        queued_count = 0
        skipped_count = 0
        for album in missing_albums.iterator():
            # Compare using album DB ID (entity_id is now str(album.id))
            if str(album.id) in albums_with_pending_tasks:
                skipped_count += 1
                continue

            if not album.is_ready_for_retry():
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


def _find_best_artist_for_deezer_id(
    normalized_name: str, artist_name: str
) -> Artist | None:
    """Among all artists with the same normalized name, return the best candidate.

    "Best" = most songs, with tracked artists preferred over untracked.
    Only considers artists that don't already have a deezer_id.
    artist_name is used for a case-insensitive pre-filter before accent normalization.
    """
    from django.db.models import Count

    candidates = (
        Artist.objects.filter(deezer_id__isnull=True, name__iexact=artist_name)
        .annotate(song_count=Count("song"))
        .order_by("-tracked", "-song_count", "id")
    )
    # Verify with accent-normalized comparison
    for candidate in candidates:
        if normalize_name(candidate.name) == normalized_name:
            return candidate
    return None


def _resolve_artist_via_isrc(
    artist: Artist, provider: DeezerMetadataProvider
) -> int | None:
    """Resolve an artist's Deezer ID by looking up their songs' ISRCs.

    Uses a quorum approach: look up 2 songs first. If both agree on
    the same Deezer artist ID, return it. If they disagree, look up 2
    more and pick the most common result.

    Only counts votes where the Deezer track's primary artist name matches
    the artist we're resolving — this prevents featured/contributing artists
    from being misidentified as the primary artist of a collaboration.

    Returns a deezer artist ID, or None if not enough data.
    """
    from ..models import Song

    songs_with_isrc = (
        Song.objects.filter(primary_artist=artist, isrc__isnull=False)
        .exclude(isrc="")
        .values_list("isrc", flat=True)[:4]
    )

    isrcs = list(songs_with_isrc)
    if not isrcs:
        return None

    normalized_artist = normalize_name(artist.name)
    votes: list[int] = []

    # First pass: check 2 ISRCs
    for isrc in isrcs[:2]:
        result = provider.get_track_by_isrc(isrc)
        if result and result.artist_deezer_id:
            if normalize_name(result.artist_name or "") == normalized_artist:
                votes.append(result.artist_deezer_id)

    if not votes:
        return None

    # If both agree, we're done
    if len(votes) >= 2 and votes[0] == votes[1]:
        return votes[0]

    # Disagreement or only 1 result — check remaining ISRCs
    for isrc in isrcs[2:]:
        result = provider.get_track_by_isrc(isrc)
        if result and result.artist_deezer_id:
            if normalize_name(result.artist_name or "") == normalized_artist:
                votes.append(result.artist_deezer_id)

    if not votes:
        return None

    # Pick the most common deezer artist ID
    from collections import Counter

    counts = Counter(votes)
    winner, winner_count = counts.most_common(1)[0]

    # Require at least 2 votes for the winner (quorum)
    if winner_count < 2:
        logger.debug(
            f"ISRC lookup for '{artist.name}': no quorum " f"(votes: {dict(counts)})"
        )
        return None

    return winner


def _assign_deezer_id_to_best_artist(
    artist: Artist, deezer_id: int, method: str
) -> Artist | None:
    """Assign a deezer_id to the best artist record with this name.

    Checks for existing ownership, picks the best candidate among
    same-name artists, and saves. Returns the linked Artist or None.
    """
    existing = Artist.objects.filter(deezer_id=deezer_id).first()
    if existing:
        logger.info(
            f"Skipping '{artist.name}' (id={artist.id}): "
            f"deezer_id {deezer_id} already belongs to "
            f"'{existing.name}' (id={existing.id})"
        )
        return None

    normalized = normalize_name(artist.name)
    best = _find_best_artist_for_deezer_id(normalized, artist.name)
    target = best if best else artist

    target.deezer_id = deezer_id
    target.save(update_fields=["deezer_id"])
    if target.id != artist.id:
        logger.info(
            f"Linked '{target.name}' (id={target.id}) to Deezer ID "
            f"{deezer_id} via {method} (preferred over id={artist.id})"
        )
    else:
        logger.info(f"Linked '{target.name}' to Deezer ID {deezer_id} via {method}")
    return target


def _try_link_artist_to_deezer(
    artist: Artist, provider: DeezerMetadataProvider
) -> Artist | None:
    """Try to link an artist to their Deezer ID.

    Resolution order:
    1. ISRC reverse-lookup (quorum of 2+ songs agreeing on same artist)
    2. Name search fallback

    If multiple Artist records share the same name, assigns the deezer_id
    to the one with the most content (songs, tracked status).

    Returns the Artist that was linked, or None if no match found.
    """
    # Try ISRC reverse-lookup first (most reliable)
    isrc_result = _resolve_artist_via_isrc(artist, provider)
    if isrc_result:
        return _assign_deezer_id_to_best_artist(artist, isrc_result, "ISRC")

    # Fall back to name search
    results = provider.search_artists(artist.name, limit=3)
    normalized = normalize_name(artist.name)
    match = next(
        (r for r in results if normalize_name(r.name) == normalized and r.deezer_id),
        None,
    )
    if not match or not match.deezer_id:
        return None

    return _assign_deezer_id_to_best_artist(artist, match.deezer_id, "name search")


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
                    linked_artist = _try_link_artist_to_deezer(artist, provider)
                    if not linked_artist:
                        artist.last_synced_at = timezone.now()
                        artist.save(update_fields=["last_synced_at"])
                        skipped_unchanged += 1
                        continue
                    linked_count += 1
                    # If a different artist got the deezer_id, skip this one
                    if linked_artist.id != artist.id:
                        artist.last_synced_at = timezone.now()
                        artist.save(update_fields=["last_synced_at"])
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


@celery_app.task(
    bind=True, name="library_manager.tasks.scan_new_releases_for_tracked_artists"
)
def scan_new_releases_for_tracked_artists(self: Any) -> None:
    """No-op stub — this task was removed but persists in the Beat DB schedule.

    TODO: Re-implement as a dedicated new-release scanner (separate from
    sync_tracked_artists_metadata which already detects new albums).
    """
    logger.info("scan_new_releases_for_tracked_artists is a no-op stub, skipping")
