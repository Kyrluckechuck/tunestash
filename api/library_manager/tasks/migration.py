"""Deezer catalog migration tasks.

Links existing Album and Song records to their Deezer counterparts
using ISRC matching (songs) and name matching (albums), then creates
new records for any Deezer content not yet in the DB.
"""

from typing import Any, Optional

from celery_app import app as celery_app

from src.providers.metadata_base import TrackResult

from ..helpers import generate_task_id, is_task_pending_or_running
from ..models import Album, Artist, Song
from ..task_priorities import TaskPriority
from .core import (
    complete_task,
    create_task_history,
    logger,
    normalize_name,
    update_task_progress,
)
from .periodic import _try_link_artist_to_deezer


def _find_matching_song(track: TrackResult, artist: Artist) -> Optional[Song]:
    """Find an existing Song that matches the given Deezer track.

    Match priority: ISRC > deezer_id > normalized name.
    """
    # Match 1: ISRC (most reliable)
    if track.isrc:
        match = Song.objects.filter(isrc=track.isrc, primary_artist=artist).first()
        if match:
            return match

    # Match 2: deezer_id (defensive — shouldn't happen since caller checks)
    match = Song.objects.filter(deezer_id=track.deezer_id).first()
    if match:
        return match

    # Match 3: Fuzzy name match (for songs without ISRC)
    normalized_track_name = normalize_name(track.name)
    candidates = Song.objects.filter(primary_artist=artist, deezer_id__isnull=True)
    for candidate in candidates:
        if normalize_name(candidate.name) == normalized_track_name:
            return candidate

    return None


def _link_or_create_song(
    track: TrackResult, artist: Artist, album: Album
) -> Optional[str]:
    """Link an existing song to Deezer or create a new one.

    Returns 'linked', 'created', or None (already linked / skipped).
    """
    if not track.deezer_id:
        return None

    if Song.objects.filter(deezer_id=track.deezer_id).exists():
        return None

    matched_song = _find_matching_song(track, artist)

    if matched_song:
        if not matched_song.deezer_id:
            # Song has no deezer_id yet — link it to this track/album
            update_fields: list[str] = ["deezer_id"]
            matched_song.deezer_id = track.deezer_id
            if not matched_song.isrc and track.isrc:
                matched_song.isrc = track.isrc
                update_fields.append("isrc")
            if matched_song.album is None:
                matched_song.album = album
                update_fields.append("album_id")
            matched_song.save(update_fields=update_fields)
            return "linked"

        # Match has a different deezer_id — this is a variant release
        # (e.g., deluxe edition, compilation). Create a separate Song
        # so each album has its own track with correct metadata.
        Song.objects.create(
            name=track.name,
            deezer_id=track.deezer_id,
            isrc=track.isrc,
            primary_artist=artist,
            album=album,
        )
        return "created"

    Song.objects.create(
        name=track.name,
        deezer_id=track.deezer_id,
        isrc=track.isrc,
        primary_artist=artist,
        album=album,
    )
    return "created"


@celery_app.task(
    bind=True,
    name="library_manager.tasks.migrate_artist_to_deezer",
)
def migrate_artist_to_deezer(self: Any, artist_id: int) -> None:
    """Migrate a single artist's catalog to Deezer IDs.

    For the given artist (which must already have a deezer_id):
    1. Fetch all albums from Deezer
    2. Match/create Album records by deezer_id or normalized name
    3. For each album, fetch tracks and match/create Song records by ISRC,
       deezer_id, or fuzzy name+duration
    """
    task_history = None
    try:
        try:
            artist = Artist.objects.get(id=artist_id)
        except Artist.DoesNotExist:
            logger.warning(f"Artist {artist_id} does not exist, skipping migration")
            return

        if not artist.deezer_id:
            logger.warning(
                f"Artist '{artist.name}' has no deezer_id, skipping migration"
            )
            return

        artist.deezer_migration_status = "in_progress"
        artist.save(update_fields=["deezer_migration_status"])

        task_history = create_task_history(
            task_id=self.request.id,
            task_type="MIGRATION",
            entity_id=str(artist.id),
            entity_type="ARTIST",
            task_name="migrate_artist_to_deezer",
        )
        task_history.status = "RUNNING"
        task_history.save()
        update_task_progress(
            task_history,
            0.0,
            f"Starting Deezer migration for {artist.name}",
        )

        from src.providers.deezer import DeezerMetadataProvider

        provider = DeezerMetadataProvider()

        # --- Phase 1: Album matching ---
        deezer_albums = provider.get_artist_albums(artist.deezer_id)
        update_task_progress(
            task_history,
            10.0,
            f"Fetched {len(deezer_albums)} albums from Deezer",
        )

        albums_linked = 0
        albums_created = 0

        for album_data in deezer_albums:
            if not album_data.deezer_id:
                continue

            # Try matching by deezer_id first
            existing = Album.objects.filter(deezer_id=album_data.deezer_id).first()
            if existing:
                continue

            # Try matching by normalized name for this artist
            normalized_deezer_name = normalize_name(album_data.name)
            name_match = None
            for db_album in Album.objects.filter(artist=artist):
                if normalize_name(db_album.name) == normalized_deezer_name:
                    name_match = db_album
                    break

            if name_match:
                update_fields: list[str] = []
                if not name_match.deezer_id:
                    name_match.deezer_id = album_data.deezer_id
                    update_fields.append("deezer_id")
                if not name_match.album_group and album_data.album_group:
                    name_match.album_group = album_data.album_group
                    update_fields.append("album_group")
                elif not name_match.album_group and album_data.album_type:
                    name_match.album_group = album_data.album_type
                    update_fields.append("album_group")
                if not name_match.album_type and album_data.album_type:
                    name_match.album_type = album_data.album_type
                    update_fields.append("album_type")
                if (
                    name_match.total_tracks == 0
                    and album_data.total_tracks
                    and album_data.total_tracks > 0
                ):
                    name_match.total_tracks = album_data.total_tracks
                    update_fields.append("total_tracks")
                if update_fields:
                    name_match.save(update_fields=update_fields)
                    albums_linked += 1
            else:
                Album.objects.create(
                    name=album_data.name,
                    deezer_id=album_data.deezer_id,
                    artist=artist,
                    spotify_uri="",
                    total_tracks=album_data.total_tracks or 0,
                    album_type=album_data.album_type,
                    album_group=album_data.album_group or album_data.album_type,
                    wanted=True,
                )
                albums_created += 1

        update_task_progress(
            task_history,
            40.0,
            f"Albums: {albums_linked} linked, {albums_created} created",
        )

        # --- Phase 2: Song matching ---
        albums_with_deezer = Album.objects.filter(
            artist=artist, deezer_id__isnull=False
        )
        songs_linked = 0
        songs_created = 0
        albums_failed = 0
        total_albums = albums_with_deezer.count()

        for idx, album in enumerate(albums_with_deezer.iterator()):
            try:
                deezer_tracks = provider.get_album_tracks(album.deezer_id)
            except Exception as e:
                logger.warning(
                    f"Failed to fetch tracks for album '{album.name}' "
                    f"(deezer_id={album.deezer_id}): {e}"
                )
                albums_failed += 1
                continue

            # Update total_tracks from actual track count if it was unknown
            actual_count = len(deezer_tracks)
            if album.total_tracks == 0 and actual_count > 0:
                album.total_tracks = actual_count
                album.save(update_fields=["total_tracks"])

            for track in deezer_tracks:
                result = _link_or_create_song(track, artist, album)
                if result == "linked":
                    songs_linked += 1
                elif result == "created":
                    songs_created += 1

            # Progress: 40-95% spread across albums
            if total_albums > 0:
                progress = 40.0 + (55.0 * (idx + 1) / total_albums)
                update_task_progress(
                    task_history,
                    progress,
                    f"Processed album {idx + 1}/{total_albums}: {album.name}",
                )

        # Mark complete
        artist.deezer_migration_status = "complete"
        artist.save(update_fields=["deezer_migration_status"])

        failed_suffix = f", {albums_failed} albums failed" if albums_failed else ""
        summary = (
            f"Deezer migration complete for {artist.name}: "
            f"albums ({albums_linked} linked, {albums_created} created), "
            f"songs ({songs_linked} linked, {songs_created} created)"
            f"{failed_suffix}"
        )
        logger.info(summary)
        update_task_progress(task_history, 100.0, summary)
        complete_task(task_history)

    except Exception as e:
        logger.exception(f"Error migrating artist {artist_id} to Deezer: {e}")
        try:
            artist_obj = Artist.objects.get(id=artist_id)
            artist_obj.deezer_migration_status = "failed"
            artist_obj.save(update_fields=["deezer_migration_status"])
        except Artist.DoesNotExist:
            pass
        if task_history:
            complete_task(task_history, success=False, error_message=str(e))
        raise


@celery_app.task(
    bind=True,
    name="library_manager.tasks.migrate_all_tracked_artists_to_deezer",
)
def migrate_all_tracked_artists_to_deezer(self: Any) -> None:
    """Orchestrator: queue per-artist Deezer migration for all eligible artists.

    Finds all artists that have a deezer_id but haven't been migrated yet
    (status is not 'complete') and queues migrate_artist_to_deezer for each.
    """
    from django.db.models import Q

    task_history = create_task_history(
        task_id=self.request.id,
        task_type="MIGRATION",
        entity_type="SYSTEM",
        task_name="migrate_all_tracked_artists_to_deezer",
    )
    task_history.status = "RUNNING"
    task_history.save()

    try:
        # Order by tracked DESC so tracked artists are queued first.
        # The PostgreSQL broker uses FIFO ordering, so queue insertion
        # order determines processing order.
        artists = (
            Artist.objects.filter(
                deezer_id__isnull=False,
            )
            .filter(
                Q(deezer_migration_status__isnull=True)
                | ~Q(deezer_migration_status="complete")
            )
            .order_by("-tracked", "id")
        )

        total = artists.count()
        if total == 0:
            msg = "No artists need Deezer migration"
            logger.info(msg)
            update_task_progress(task_history, 100.0, msg)
            complete_task(task_history)
            return

        queued_tracked = 0
        queued_untracked = 0
        skipped = 0
        for artist in artists:
            task_id = generate_task_id(
                "library_manager.tasks.migrate_artist_to_deezer", artist.id
            )
            is_pending, reason = is_task_pending_or_running(task_id)
            if is_pending:
                logger.debug(f"[DEDUP] Skipping migration for {artist.name}: {reason}")
                skipped += 1
                continue

            if artist.deezer_migration_status != "in_progress":
                artist.deezer_migration_status = "pending"
                artist.save(update_fields=["deezer_migration_status"])

            migrate_artist_to_deezer.apply_async(args=[artist.id], task_id=task_id)
            if artist.tracked:
                queued_tracked += 1
            else:
                queued_untracked += 1

        summary = (
            f"Deezer migration orchestrator: queued {queued_tracked} tracked + "
            f"{queued_untracked} untracked artists, "
            f"skipped {skipped} (already pending), {total} total eligible"
        )
        logger.info(summary)
        update_task_progress(task_history, 100.0, summary)
        complete_task(task_history)

    except Exception as e:
        logger.exception(f"Error in migrate_all_tracked_artists_to_deezer: {e}")
        complete_task(task_history, success=False, error_message=str(e))
        raise


@celery_app.task(
    bind=True,
    name="library_manager.tasks.resolve_all_artists_to_deezer",
)
def resolve_all_artists_to_deezer(
    self: Any,
    batch_size: int = 200,
    last_artist_id: int = 0,
    tracked_only: bool = True,
) -> None:
    """Resolve artists without a deezer_id by searching Deezer by name.

    Processes artists in batches, self-chaining until complete.
    Tracked artists are processed first (tracked_only=True), then
    automatically continues with untracked artists.

    Args:
        batch_size: Number of artists to process per task invocation.
        last_artist_id: ID cursor for pagination (set automatically).
        tracked_only: If True, only process tracked artists (first pass).
    """
    import time

    from src.providers.deezer import DeezerMetadataProvider

    task_history = create_task_history(
        task_id=self.request.id,
        task_type="MIGRATION",
        entity_type="SYSTEM",
        task_name="resolve_all_artists_to_deezer",
    )
    task_history.status = "RUNNING"
    task_history.save()

    try:
        queryset = Artist.objects.filter(
            deezer_id__isnull=True,
            id__gt=last_artist_id,
        ).order_by("id")

        if tracked_only:
            queryset = queryset.filter(tracked=True)

        artists = list(queryset[:batch_size])

        if not artists:
            if tracked_only:
                # Tracked pass done — continue with untracked artists
                untracked_remaining = Artist.objects.filter(
                    deezer_id__isnull=True, tracked=False
                ).count()
                if untracked_remaining > 0:
                    msg = (
                        f"Tracked artists resolved. "
                        f"Continuing with {untracked_remaining} untracked artists."
                    )
                    logger.info(msg)
                    update_task_progress(task_history, 100.0, msg)
                    complete_task(task_history)
                    resolve_all_artists_to_deezer.apply_async(
                        kwargs={
                            "batch_size": batch_size,
                            "last_artist_id": 0,
                            "tracked_only": False,
                        },
                        priority=TaskPriority.RESOLVE,
                    )
                    return

            msg = "Artist Deezer resolution complete — no more artists to process."
            logger.info(msg)
            update_task_progress(task_history, 100.0, msg)
            complete_task(task_history)
            return

        provider = DeezerMetadataProvider()
        linked = 0
        not_found = 0
        errors = 0
        max_artist_id = artists[-1].id
        scope = "tracked" if tracked_only else "all"

        total_remaining = Artist.objects.filter(
            deezer_id__isnull=True,
            id__gt=last_artist_id,
            **({"tracked": True} if tracked_only else {}),
        ).count()

        update_task_progress(
            task_history,
            0.0,
            f"Resolving batch of {len(artists)} {scope} artists "
            f"({total_remaining} remaining)",
        )

        for idx, artist in enumerate(artists):
            try:
                linked_artist = _try_link_artist_to_deezer(artist, provider)
                if linked_artist:
                    linked += 1
                else:
                    not_found += 1
            except Exception as e:
                logger.debug(f"Deezer search failed for artist '{artist.name}': {e}")
                errors += 1

            time.sleep(0.1)

            if (idx + 1) % 50 == 0:
                progress = 100.0 * (idx + 1) / len(artists)
                update_task_progress(
                    task_history,
                    progress,
                    f"Processed {idx + 1}/{len(artists)}: "
                    f"{linked} linked, {not_found} not found",
                )

        summary = (
            f"Resolved {len(artists)} {scope} artists: "
            f"{linked} linked, {not_found} not found, {errors} errors"
        )
        logger.info(summary)
        update_task_progress(task_history, 100.0, summary)
        complete_task(task_history)

        # Self-chain for next batch
        next_remaining = Artist.objects.filter(
            deezer_id__isnull=True,
            id__gt=max_artist_id,
            **({"tracked": True} if tracked_only else {}),
        ).count()

        if next_remaining > 0:
            logger.info(
                f"{next_remaining} {scope} artists remaining, " f"scheduling next batch"
            )
            resolve_all_artists_to_deezer.apply_async(
                kwargs={
                    "batch_size": batch_size,
                    "last_artist_id": max_artist_id,
                    "tracked_only": tracked_only,
                },
                priority=TaskPriority.RESOLVE,
            )
        elif tracked_only:
            # Tracked pass complete — transition to untracked artists
            untracked_remaining = Artist.objects.filter(
                deezer_id__isnull=True, tracked=False
            ).count()
            if untracked_remaining > 0:
                logger.info(
                    f"Tracked artists resolved. "
                    f"Continuing with {untracked_remaining} untracked artists."
                )
                resolve_all_artists_to_deezer.apply_async(
                    kwargs={
                        "batch_size": batch_size,
                        "last_artist_id": 0,
                        "tracked_only": False,
                    },
                    priority=TaskPriority.RESOLVE,
                )

    except Exception as e:
        logger.exception(f"Error in resolve_all_artists_to_deezer: {e}")
        complete_task(task_history, success=False, error_message=str(e))
        raise
