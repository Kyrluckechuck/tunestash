"""Playlist tasks for the Tunestash."""

from typing import Any, Optional

from django.utils import timezone

from celery_app import app as celery_app

from .. import helpers
from ..artist_credits import (
    create_song_with_credits,
    credits_for_song_release,
    ensure_song_credits,
    resolve_artist,
)
from ..models import Artist, PlaylistSong, Song, TrackedPlaylist, TrackingTier
from .core import (
    TaskPriority,
    complete_task,
    create_task_history,
    extract_deezer_playlist_id,
    is_task_cancelled,
    logger,
    update_task_progress,
)
from .migration import _find_matching_song
from .song_identity import (
    apply_identifier_updates,
    identifier_updates,
    release_track_id,
)


def _update_playlist_songs(
    playlist: TrackedPlaylist, ordered_songs: list[Song]
) -> None:
    """Sync PlaylistSong records for a playlist.

    Creates/updates entries to match the ordered list of songs.
    Removes entries for songs no longer in the playlist.
    """
    existing = {
        ps.song_id: ps  # type: ignore[attr-defined]
        for ps in PlaylistSong.objects.filter(playlist=playlist)
    }
    new_song_ids = set()

    to_create: list[PlaylistSong] = []
    to_update: list[PlaylistSong] = []

    for order, song in enumerate(ordered_songs):
        new_song_ids.add(song.id)
        if song.id in existing:
            ps = existing[song.id]
            if ps.track_order != order:
                ps.track_order = order
                to_update.append(ps)
        else:
            to_create.append(
                PlaylistSong(playlist=playlist, song=song, track_order=order)
            )

    # Remove songs no longer in playlist
    removed_ids = set(existing.keys()) - new_song_ids
    if removed_ids:
        PlaylistSong.objects.filter(playlist=playlist, song_id__in=removed_ids).delete()

    if to_create:
        PlaylistSong.objects.bulk_create(to_create, ignore_conflicts=True)
    if to_update:
        PlaylistSong.objects.bulk_update(to_update, ["track_order"])


def _generate_m3u_if_enabled(playlist: TrackedPlaylist) -> None:
    """Generate M3U file for a playlist if m3u_enabled is set."""
    if not playlist.m3u_enabled:
        return

    from pathlib import Path

    from django.conf import settings as django_settings

    from downloader.m3u_writer import write_playlist_m3u

    from src.app_settings.registry import get_setting

    output_dir = Path(getattr(django_settings, "OUTPUT_PATH", "/mnt/music_spotify"))
    playlist_dir = get_setting("m3u_playlists_directory")
    write_playlist_m3u(playlist.pk, output_dir, playlist_dir)


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


@celery_app.task(bind=True, name="library_manager.tasks.sync_deezer_playlist")
def sync_deezer_playlist(
    self: Any, playlist_id: int, task_id: Optional[str] = None
) -> None:
    """Sync a Deezer playlist: fetch tracks, match/create songs, queue downloads."""
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

        deezer_playlist_id = extract_deezer_playlist_id(playlist.url)
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
        update_task_progress(
            task_history, 0.0, f"Starting Deezer playlist sync: {playlist.name}"
        )

        from src.providers.deezer import DeezerMetadataProvider

        provider = DeezerMetadataProvider()

        if is_task_cancelled(task_history.task_id):
            logger.info("Playlist sync cancelled: %s", playlist.name)
            return

        playlist_info = provider.get_playlist(deezer_playlist_id)
        if playlist_info:
            if playlist_info.name and playlist_info.name != playlist.name:
                playlist.name = playlist_info.name
            playlist.snapshot_id = playlist_info.checksum
            playlist.save(update_fields=["name", "snapshot_id"])

        update_task_progress(task_history, 10.0, "Fetching playlist tracks from Deezer")

        if is_task_cancelled(task_history.task_id):
            logger.info("Playlist sync cancelled: %s", playlist.name)
            return

        tracks = provider.get_playlist_tracks(deezer_playlist_id)
        update_task_progress(task_history, 20.0, f"Processing {len(tracks)} tracks")

        new_songs = 0
        linked_songs = 0
        downloads_queued = 0
        total = len(tracks)
        ordered_songs: list[Song] = []

        for idx, track in enumerate(tracks):
            if is_task_cancelled(task_history.task_id):
                logger.info("Playlist sync cancelled: %s", playlist.name)
                return
            if not track.deezer_id:
                continue

            # Try matching existing song
            # 1. By ISRC
            matched_song = None
            freshly_created = False
            if track.isrc:
                matched_song = Song.objects.filter(isrc=track.isrc).first()
            # 2. By deezer_id
            if not matched_song:
                matched_song = Song.objects.filter(deezer_id=track.deezer_id).first()

            if matched_song:
                # Fill only identifiers that are missing and non-conflicting. The
                # ISRC match may be the same recording on another release, whose
                # track id must not be stored on this album's row.
                updates = identifier_updates(
                    matched_song, release_track_id(matched_song, track), track.isrc
                )
                if updates:
                    apply_identifier_updates(matched_song, updates)
                    linked_songs += 1
            else:
                artist = resolve_artist(
                    track.artist_name,
                    deezer_id=track.artist_deezer_id,
                    evidence_isrcs=[track.isrc],
                )
                if artist is None:
                    logger.warning(
                        "Skipping Deezer track %s: artist has no id or is an "
                        "unverified same-name match",
                        track.deezer_id,
                    )
                    continue

                # Use _find_matching_song for fuzzy name match
                matched_song = _find_matching_song(track, artist)
                if matched_song:
                    updates = identifier_updates(
                        matched_song, release_track_id(matched_song, track), track.isrc
                    )
                    if updates:
                        apply_identifier_updates(matched_song, updates)
                        linked_songs += 1
                else:
                    matched_song = create_song_with_credits(track)
                    if matched_song is None:
                        continue
                    new_songs += 1
                    freshly_created = True

            if matched_song and not freshly_created:
                ensure_song_credits(
                    matched_song, credits_for_song_release(matched_song, track)
                )
                matched_song.refresh_from_db(fields=["primary_artist"])
            if matched_song:
                ordered_songs.append(matched_song)

            if (
                matched_song
                and matched_song.bitrate == 0
                and not matched_song.unavailable
            ):
                if helpers.enqueue_download_deezer_track(
                    matched_song.id, priority=TaskPriority.TRACK_DOWNLOAD
                ):
                    downloads_queued += 1

            if total > 0 and (idx + 1) % 50 == 0:
                progress = 20.0 + (70.0 * (idx + 1) / total)
                update_task_progress(
                    task_history,
                    progress,
                    f"Processed {idx + 1}/{total} tracks",
                )

        # Update PlaylistSong records and generate M3U
        _update_playlist_songs(playlist, ordered_songs)
        _generate_m3u_if_enabled(playlist)

        if playlist.auto_track_tier is not None:
            artist_deezer_ids = [
                t.artist_deezer_id for t in tracks if t.artist_deezer_id
            ]
            if artist_deezer_ids:
                artists_to_track = Artist.objects.filter(
                    deezer_id__in=artist_deezer_ids
                ).exclude(tracking_tier__gte=playlist.auto_track_tier)
                updated = artists_to_track.update(
                    tracking_tier=playlist.auto_track_tier
                )
                if updated:
                    logger.info(
                        f"Marked {updated} artists at tier {playlist.auto_track_tier} "
                        f"from playlist '{playlist.name}'"
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

    deezer_playlist_id = extract_deezer_playlist_id(playlist.url)
    if not deezer_playlist_id:
        logger.error(f"Could not extract Deezer playlist ID from URL: {playlist.url}")
        return

    provider = DeezerMetadataProvider()
    tracks = provider.get_playlist_tracks(deezer_playlist_id)

    if playlist.auto_track_tier is None:
        logger.info(
            f"Auto-track disabled for '{playlist.name}', skipping artist tracking"
        )
        return
    tier = playlist.auto_track_tier

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
            defaults={"name": name, "tracking_tier": tier},
        )
        if created:
            tracked_count += 1
        else:
            Artist.objects.filter(
                deezer_id=deezer_id, tracking_tier=TrackingTier.UNTRACKED
            ).update(tracking_tier=tier)

    # Count how many were updated (not just created)
    total_tracked = Artist.objects.filter(
        deezer_id__in=list(seen_artist_ids), tracking_tier__gte=1
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
            f"Spotify playlists track artists during download"
        )
