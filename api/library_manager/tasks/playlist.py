"""Playlist tasks for the Spotify library manager."""

import re
from typing import Any, Optional

from django.utils import timezone

from celery_app import app as celery_app

from .. import helpers
from ..models import Artist, Song, TrackedPlaylist
from .core import complete_task, create_task_history, logger, update_task_progress
from .migration import _find_matching_song


def _sync_tracked_playlist_internal(
    tracked_playlist: TrackedPlaylist, task_id: Optional[str] = None
) -> None:
    """Internal function that does the actual sync work"""
    task_history = None
    try:
        # Create task history record for the sync operation
        task_history = create_task_history(
            task_id=task_id,
            task_type="SYNC",
            entity_id=str(tracked_playlist.pk),
            entity_type="PLAYLIST",
            task_name="sync_tracked_playlist",
        )
        update_task_progress(
            task_history, 0.0, f"Starting playlist sync: {tracked_playlist.name}"
        )
        # Mark as running
        task_history.status = "RUNNING"
        task_history.save()

        # Enqueue the actual download task
        priority = 2  # Default priority since task.priority not available in Celery
        helpers.enqueue_playlists([tracked_playlist], priority=priority)

        # Mark as completed since the sync operation is done (download is queued separately)
        complete_task(task_history, success=True)

    except Exception as e:
        if task_history:
            complete_task(task_history, success=False, error_message=str(e))
        raise


@celery_app.task(bind=True, name="library_manager.tasks.sync_tracked_playlist")
def sync_tracked_playlist(
    self: Any, playlist_id: int, task_id: Optional[str] = None
) -> None:
    """Celery task wrapper for sync_tracked_playlist"""
    # Use the Celery task ID if no task_id is provided
    if task_id is None:
        task_id = self.request.id

    # Get the playlist object from the ID
    try:
        tracked_playlist = TrackedPlaylist.objects.get(id=playlist_id)
    except TrackedPlaylist.DoesNotExist:
        logger.warning(
            f"TrackedPlaylist with ID {playlist_id} does not exist. Skipping task."
        )
        return

    _sync_tracked_playlist_internal(tracked_playlist, task_id)


def _extract_deezer_playlist_id(url: str) -> Optional[str]:
    """Extract the numeric playlist ID from a Deezer playlist URL."""
    match = re.search(r"deezer\.com/(?:\w+/)?playlist/(\d+)", url)
    return match.group(1) if match else None


@celery_app.task(bind=True, name="library_manager.tasks.sync_deezer_playlist")
def sync_deezer_playlist(
    self: Any, playlist_id: int, task_id: Optional[str] = None
) -> None:
    """Sync a Deezer playlist: fetch tracks, match/create songs, queue downloads."""
    from .download import download_deezer_track

    task_history = None
    try:
        try:
            playlist = TrackedPlaylist.objects.get(id=playlist_id)
        except TrackedPlaylist.DoesNotExist:
            logger.warning(
                f"TrackedPlaylist with ID {playlist_id} does not exist. Skipping."
            )
            return

        if playlist.provider != "deezer":
            logger.warning(
                f"Playlist {playlist_id} is not a Deezer playlist "
                f"(provider={playlist.provider}). Skipping."
            )
            return

        deezer_playlist_id = _extract_deezer_playlist_id(playlist.url)
        if not deezer_playlist_id:
            logger.error(
                f"Could not extract Deezer playlist ID from URL: {playlist.url}"
            )
            return

        task_history = create_task_history(
            task_id=task_id or self.request.id,
            task_type="SYNC",
            entity_id=str(playlist.pk),
            entity_type="PLAYLIST",
            task_name="sync_deezer_playlist",
        )
        task_history.status = "RUNNING"
        task_history.save()
        update_task_progress(
            task_history, 0.0, f"Starting Deezer playlist sync: {playlist.name}"
        )

        from src.providers.deezer import DeezerMetadataProvider

        provider = DeezerMetadataProvider()

        # Fetch playlist metadata and update name/checksum
        playlist_info = provider.get_playlist(deezer_playlist_id)
        if playlist_info:
            if playlist_info.name and playlist_info.name != playlist.name:
                playlist.name = playlist_info.name
            playlist.snapshot_id = playlist_info.checksum
            playlist.save(update_fields=["name", "snapshot_id"])

        update_task_progress(task_history, 10.0, "Fetching playlist tracks from Deezer")

        # Fetch all tracks
        tracks = provider.get_playlist_tracks(deezer_playlist_id)
        update_task_progress(task_history, 20.0, f"Processing {len(tracks)} tracks")

        new_songs = 0
        linked_songs = 0
        downloads_queued = 0
        total = len(tracks)

        for idx, track in enumerate(tracks):
            if not track.deezer_id:
                continue

            # Try matching existing song
            # 1. By ISRC
            matched_song = None
            if track.isrc:
                matched_song = Song.objects.filter(isrc=track.isrc).first()
            # 2. By deezer_id
            if not matched_song:
                matched_song = Song.objects.filter(deezer_id=track.deezer_id).first()

            if matched_song:
                # Update deezer_id/isrc if missing
                update_fields: list[str] = []
                if not matched_song.deezer_id:
                    matched_song.deezer_id = track.deezer_id
                    update_fields.append("deezer_id")
                if not matched_song.isrc and track.isrc:
                    matched_song.isrc = track.isrc
                    update_fields.append("isrc")
                if update_fields:
                    matched_song.save(update_fields=update_fields)
                    linked_songs += 1
            else:
                # Find or create artist
                artist = None
                if track.artist_deezer_id:
                    artist = Artist.objects.filter(
                        deezer_id=track.artist_deezer_id
                    ).first()
                if not artist:
                    artist, _ = Artist.objects.get_or_create(
                        deezer_id=track.artist_deezer_id,
                        defaults={"name": track.artist_name},
                    )

                # Use _find_matching_song for fuzzy name match
                matched_song = _find_matching_song(track, artist)
                if matched_song:
                    update_fields = []
                    if not matched_song.deezer_id:
                        matched_song.deezer_id = track.deezer_id
                        update_fields.append("deezer_id")
                    if not matched_song.isrc and track.isrc:
                        matched_song.isrc = track.isrc
                        update_fields.append("isrc")
                    if update_fields:
                        matched_song.save(update_fields=update_fields)
                        linked_songs += 1
                else:
                    # Create new song
                    matched_song = Song.objects.create(
                        name=track.name,
                        deezer_id=track.deezer_id,
                        isrc=track.isrc,
                        primary_artist=artist,
                    )
                    new_songs += 1

            # Queue download if not downloaded
            if (
                matched_song
                and matched_song.bitrate == 0
                and not matched_song.unavailable
            ):
                download_deezer_track.delay(matched_song.id)
                downloads_queued += 1

            # Update progress
            if total > 0 and (idx + 1) % 50 == 0:
                progress = 20.0 + (70.0 * (idx + 1) / total)
                update_task_progress(
                    task_history,
                    progress,
                    f"Processed {idx + 1}/{total} tracks",
                )

        # Mark artists as tracked if auto_track_artists is enabled
        if playlist.auto_track_artists:
            artist_deezer_ids = [
                t.artist_deezer_id for t in tracks if t.artist_deezer_id
            ]
            if artist_deezer_ids:
                artists_to_track = Artist.objects.filter(
                    deezer_id__in=artist_deezer_ids
                ).exclude(tracked=True)
                updated = artists_to_track.update(tracked=True)
                if updated:
                    logger.info(
                        f"Marked {updated} artists as tracked from "
                        f"playlist '{playlist.name}'"
                    )

        playlist.last_synced_at = timezone.now()
        playlist.save(update_fields=["last_synced_at"])

        summary = (
            f"Deezer playlist sync complete for '{playlist.name}': "
            f"{total} tracks, {new_songs} new, {linked_songs} linked, "
            f"{downloads_queued} downloads queued"
        )
        logger.info(summary)
        update_task_progress(task_history, 100.0, summary)
        complete_task(task_history)

    except Exception as e:
        logger.exception(f"Error syncing Deezer playlist {playlist_id}: {e}")
        if task_history:
            complete_task(task_history, success=False, error_message=str(e))
        raise


def _track_artists_in_deezer_playlist(playlist: TrackedPlaylist) -> None:
    """Track all artists in a Deezer playlist by fetching tracks from Deezer API."""
    from src.providers.deezer import DeezerMetadataProvider

    deezer_playlist_id = _extract_deezer_playlist_id(playlist.url)
    if not deezer_playlist_id:
        logger.error(f"Could not extract Deezer playlist ID from URL: {playlist.url}")
        return

    provider = DeezerMetadataProvider()
    tracks = provider.get_playlist_tracks(deezer_playlist_id)

    # Collect unique artist deezer_ids and names
    seen_artist_ids: set[int] = set()
    artists_data: list[tuple[int, str]] = []
    for track in tracks:
        if track.artist_deezer_id and track.artist_deezer_id not in seen_artist_ids:
            seen_artist_ids.add(track.artist_deezer_id)
            artists_data.append(
                (track.artist_deezer_id, track.artist_name or "Unknown Artist")
            )

    tracked_count = 0
    for deezer_id, name in artists_data:
        _, created = Artist.objects.get_or_create(
            deezer_id=deezer_id,
            defaults={"name": name, "tracked": True},
        )
        if created:
            tracked_count += 1
        else:
            Artist.objects.filter(deezer_id=deezer_id, tracked=False).update(
                tracked=True
            )

    # Count how many were updated (not just created)
    total_tracked = Artist.objects.filter(
        deezer_id__in=list(seen_artist_ids), tracked=True
    ).count()
    logger.info(
        f"Tracked {total_tracked} artists from Deezer playlist '{playlist.name}' "
        f"({tracked_count} newly created)"
    )


@celery_app.task(bind=True, name="library_manager.tasks.sync_tracked_playlist_artists")
def sync_tracked_playlist_artists(
    self: Any, playlist_id: int, task_id: Optional[str] = None
) -> None:
    """Track artists from a playlist without downloading it."""
    try:
        playlist = TrackedPlaylist.objects.get(id=playlist_id)
    except TrackedPlaylist.DoesNotExist:
        logger.warning(
            f"TrackedPlaylist with ID {playlist_id} does not exist. Skipping task."
        )
        return

    if playlist.provider == "deezer":
        _track_artists_in_deezer_playlist(playlist)
    else:
        logger.info(
            f"Skipping artist tracking for Spotify playlist '{playlist.name}' — "
            f"artists are tracked during download via spotdl"
        )
